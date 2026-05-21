#!/usr/bin/env python3
"""Validate price cache before reports or alerts use it.

The validator is intentionally conservative: it does not fill missing prices
and it marks large changes for confirmation instead of turning them into facts.
"""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

from runtime_logger import log_event, log_exception


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
THRESHOLDS_FILE = CONFIG_DIR / "thresholds.json"
TREND_HISTORY_DIR = DATA_DIR / "trend_history"
VALIDATION_REPORT_FILE = DATA_DIR / "validation_report.json"
ANOMALY_VOTES_FILE = DATA_DIR / "anomaly_votes.json"


PRICE_PATHS = {
    "xianyu_market": [
        ("xianyu_market", "price"),
        ("xianyu_market", "median"),
        ("xianyu_market", "avg"),
        ("xianyu_market", "avg_price"),
        ("xianyu_market_price",),
        ("闲鱼自由市场价格",),
        ("二手均价",),
    ],
    "xianyu_official": [("xianyu_official", "price")],
    "aihuishou": [
        ("aihuishou", "tansuo_price"),
        ("aihuishou", "after_coupon"),
        ("aihuishou", "base_price"),
        ("aihuishou_price",),
        ("爱回收价格",),
    ],
    "zhuanzhuan_recycle": [
        ("zhuanzhuan_recycle", "price"),
        ("zhuanzhuan", "price"),
        ("zhuanzhuan_price",),
        ("转转回收价格",),
    ],
}


def now_iso():
    return datetime.now().isoformat()


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def load_json(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def nested_get(data, path):
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def nested_first(data, paths):
    for path in paths:
        value = nested_get(data, path)
        if as_number(value) is not None:
            return value
    return None


def as_number(value):
    if value in (None, "", "—", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        numbers = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
        if not numbers:
            return None
        parsed = [float(item) for item in numbers]
        return sum(parsed[:2]) / min(len(parsed), 2)


def is_pc_hardware(product_id, product_name):
    text = f"{product_id} {product_name}".lower()
    keys = ["rtx", "rx_", "显卡", "i5", "i7", "cpu", "ddr", "nand", "ssd", "固态", "内存", "amd"]
    return any(key in text for key in keys)


def load_previous_product(product_id, current_scan_date):
    product_dir = TREND_HISTORY_DIR / product_id
    if not product_dir.exists():
        return None
    candidates = sorted(product_dir.glob("*.json"), reverse=True)
    for path in candidates:
        if path.stem >= current_scan_date:
            continue
        data = load_json(path)
        if data.get("data"):
            return data["data"]
    return None


def pct_change(current, previous):
    if previous in (None, 0) or current is None:
        return None
    return (current - previous) / previous * 100


def has_any_price(item):
    return any(
        (value is not None and value >= 1)
        for value in (as_number(nested_first(item, paths)) for paths in PRICE_PATHS.values())
    )


def product_validation_rules(thresholds, product_id, product_name):
    validation = thresholds.get("validation", {})
    text = f"{product_id} {product_name}".lower()
    rules = {
        "price_min": float(validation.get("price_min", 1)),
        "exclude_keywords": validation.get("exclude_keywords", []),
    }
    product_min = (validation.get("product_price_min") or {}).get(product_id)
    if product_min is not None:
        rules["price_min"] = float(product_min)
    for keyword, floor in (validation.get("keyword_price_min") or {}).items():
        if str(keyword).lower() in text:
            rules["price_min"] = max(rules["price_min"], float(floor))
    return rules


def sample_text(sample):
    if isinstance(sample, dict):
        return " ".join(str(sample.get(key) or "") for key in ("title", "name", "desc", "description", "note"))
    return str(sample or "")


def has_excluded_sample(item, exclude_keywords):
    samples = nested_get(item, ("xianyu_market", "samples")) or []
    if not isinstance(samples, list):
        samples = [samples]
    for sample in samples:
        text = sample_text(sample).lower()
        if any(str(keyword).lower() in text for keyword in exclude_keywords):
            return True
    return False


def classify_signal(vote_count, drop_pct, confidence, thresholds):
    levels = thresholds.get("signal_levels", {})
    s = levels.get("S", {})
    a = levels.get("A", {})
    if (
        vote_count >= int(s.get("vote_count_min", 3))
        and drop_pct is not None
        and drop_pct <= -float(s.get("drop_pct_min", 30.0))
        and confidence >= float(s.get("confidence_min", 90))
    ):
        return "S"
    if (
        vote_count >= int(a.get("vote_count_min", 3))
        and confidence >= float(a.get("confidence_min", 70))
        and confidence < float(a.get("confidence_max", 90))
    ):
        return "A"
    return "B"


def validate_cache(cache, thresholds):
    validation = thresholds.get("validation", {})
    price_min = float(validation.get("price_min", 1))
    price_max = float(validation.get("price_max", 100000))
    warn_change = float(validation.get("warn_change_pct", 20.0))
    manual_change = float(validation.get("manual_confirm_change_pct", 30.0))
    scan_date = cache.get("scan_time") or today_str()

    prices = cache.get("prices") or cache.get("models") or {}
    report = {
        "version": "1.0.0",
        "date": today_str(),
        "generated_at": now_iso(),
        "source": str(PRICE_CACHE_FILE),
        "ok": True,
        "manual_confirmation_required": False,
        "errors": [],
        "warnings": [],
        "products": {},
        "stats": {
            "product_count": len(prices),
            "valid_product_count": 0,
            "valid_price_count": 0,
        },
    }
    votes = {
        "version": "1.0.0",
        "date": today_str(),
        "generated_at": now_iso(),
        "source": "price_data_validator",
        "items": [],
    }

    for product_id, item in prices.items():
        product_name = item.get("product_name") or product_id
        previous = load_previous_product(product_id, scan_date)
        product_has_price = has_any_price(item)
        if product_has_price:
            report["stats"]["valid_product_count"] += 1
        product_result = {
            "product_id": product_id,
            "product_name": product_name,
            "status": "ok" if product_has_price else "no_valid_price",
            "warnings": [],
            "errors": [],
            "platforms": {},
        }

        rules = product_validation_rules(thresholds, product_id, product_name)
        official_price = as_number(nested_first(item, PRICE_PATHS["xianyu_official"]))

        for platform, paths in PRICE_PATHS.items():
            current = as_number(nested_first(item, paths))
            prev = as_number(nested_first(previous or {}, paths))
            platform_result = {
                "price": current,
                "previous_price": prev,
                "change_pct": None,
                "display": current if current is not None else validation.get("null_display", "—"),
                "reason": None,
                "requires_manual_confirmation": False,
            }

            if current is None:
                if is_pc_hardware(product_id, product_name) and platform in ("xianyu_official", "aihuishou"):
                    platform_result["reason"] = validation.get("normal_missing_coverage", {}).get("pc_hardware", {}).get(
                        "reason",
                        "PC硬件回收渠道覆盖率低，暂无报价是正常结果",
                    )
                else:
                    platform_result["reason"] = "本次扫描未获取到有效报价"
                product_result["platforms"][platform] = platform_result
                continue
            platform_min = rules["price_min"] if platform == "xianyu_market" else price_min
            if current < platform_min or current > price_max:
                message = f"{product_name} {platform} 价格超出合理范围: {current:g}"
                product_result["errors"].append(message)
                report["errors"].append(message)
                report["ok"] = False
                platform_result["display"] = validation.get("null_display", "—")
                platform_result["reason"] = "价格超出合理范围，已禁止用于播报"
            else:
                report["stats"]["valid_price_count"] += 1

            suspect_market_price = (
                platform == "xianyu_market"
                and official_price is not None
                and current is not None
                and current < official_price
            )
            suspect_keyword = platform == "xianyu_market" and has_excluded_sample(item, rules["exclude_keywords"])
            if suspect_market_price or suspect_keyword:
                reason = "闲鱼市场价低于官方回收价，疑似ES/QS/样品/异常低价"
                if suspect_keyword:
                    reason = "闲鱼样本命中ES/QS/工程样品等排除词"
                platform_result["reason"] = reason
                platform_result["low_confidence"] = True
                product_result["status"] = "low_confidence"
                message = f"{product_name} {platform}: {reason}"
                product_result["warnings"].append(message)
                report["warnings"].append(message)

            change = pct_change(current, prev)
            platform_result["change_pct"] = round(change, 2) if change is not None else None
            if change is not None and abs(change) > warn_change:
                message = f"{product_name} {platform} 较上次变化 {change:+.1f}%"
                product_result["warnings"].append(message)
                report["warnings"].append(message)

                vote_count = 3 if abs(change) >= manual_change else 2
                confidence = min(99, 60 + abs(change))
                level = "B" if platform_result.get("low_confidence") else classify_signal(vote_count, change, confidence, thresholds)
                votes["items"].append({
                    "product_id": product_id,
                    "product_name": product_name,
                    "platform": platform,
                    "change_pct": round(change, 2),
                    "vote_count": vote_count,
                    "confidence": round(confidence, 1),
                    "level": level,
                    "algorithms": ["consistency_check"],
                    "needs_continuous_confirmation": True,
                    "low_confidence": bool(platform_result.get("low_confidence")),
                    "reason": platform_result.get("reason"),
                })

            if change is not None and abs(change) > manual_change:
                platform_result["requires_manual_confirmation"] = True
                report["manual_confirmation_required"] = True
                product_result["status"] = "manual_confirmation_required"

            product_result["platforms"][platform] = platform_result

        if not product_has_price:
            message = f"{product_name}: 本次扫描没有任何有效价格"
            product_result["errors"].append(message)
            report["warnings"].append(message)
        if product_result["errors"] and product_has_price:
            product_result["status"] = "invalid"
        elif product_result["warnings"] and product_result["status"] == "ok":
            product_result["status"] = "warning"
        report["products"][product_id] = product_result

    if report["stats"]["product_count"] > 0 and report["stats"]["valid_price_count"] == 0:
        report["ok"] = False
        report["errors"].append("本次扫描有效价格为0，日报不得按正常行情播报")

    return report, votes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--price-cache", default=str(PRICE_CACHE_FILE))
    parser.add_argument("--report", default=str(VALIDATION_REPORT_FILE))
    parser.add_argument("--votes", default=str(ANOMALY_VOTES_FILE))
    args = parser.parse_args()
    log_event("price_validator.start", price_cache=args.price_cache, report=args.report, votes=args.votes)

    cache = load_json(Path(args.price_cache))
    thresholds = load_json(THRESHOLDS_FILE)
    report, votes = validate_cache(cache, thresholds)
    save_json(Path(args.report), report)
    save_json(Path(args.votes), votes)
    log_event(
        "price_validator.done",
        ok=report["ok"],
        manual_confirmation_required=report["manual_confirmation_required"],
        product_count=report["stats"]["product_count"],
        valid_price_count=report["stats"]["valid_price_count"],
        warnings=len(report["warnings"]),
        errors=len(report["errors"]),
        votes=len(votes.get("items", [])),
    )

    print(json.dumps({
        "ok": report["ok"],
        "manual_confirmation_required": report["manual_confirmation_required"],
        "valid_price_count": report["stats"]["valid_price_count"],
        "warnings": len(report["warnings"]),
        "errors": len(report["errors"]),
        "report": args.report,
        "votes": args.votes,
    }, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        log_exception("price_validator.exception", exc)
        raise
