#!/usr/bin/env python3
"""Record daily platform prices and enrich price_cache with day-over-day change."""
import argparse
import json
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
TREND_HISTORY_DIR = DATA_DIR / "trend_history"
DAILY_PRICE_DIR = DATA_DIR / "daily_price_records"


PLATFORM_PATHS = {
    "xianyu_market": ("xianyu_market", "avg"),
    "aihuishou": ("aihuishou", "tansuo_price"),
    "xianyu_official": ("xianyu_official", "price"),
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


def nested_set(data, path, value):
    cur = data
    for key in path[:-1]:
        cur = cur.setdefault(key, {})
    cur[path[-1]] = value


def as_number(value):
    if value in (None, "", "—", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def pct_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous * 100


def previous_product(product_id, scan_date):
    product_dir = TREND_HISTORY_DIR / product_id
    if not product_dir.exists():
        return None
    for path in sorted(product_dir.glob("*.json"), reverse=True):
        if path.stem >= scan_date:
            continue
        data = load_json(path)
        return data.get("data") or data
    return None


def infer_baseline_date(product_id, current_date):
    """从历史记录中推断基准日期（最早的记录日期），格式化为YYYY年M月"""
    product_dir = TREND_HISTORY_DIR / product_id
    if not product_dir.exists():
        return None
    # 获取最早的记录文件
    files = sorted(product_dir.glob("*.json"))
    if not files:
        return None
    earliest_file = files[0]
    # 从文件名提取日期（格式：YYYY-MM-DD.json）
    date_str = earliest_file.stem
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%Y年%-m月")
    except ValueError:
        return None


def build_daily_record(cache):
    scan_date = cache.get("scan_time") or today_str()
    records = []
    prices = cache.get("prices") or cache.get("models") or {}

    for product_id, item in prices.items():
        prev = previous_product(product_id, scan_date)
        platform_records = {}
        representative_change = None

        # 如果没有baseline_date但有历史记录，自动填充
        if not item.get("baseline_date") and prev:
            inferred_date = infer_baseline_date(product_id, scan_date)
            if inferred_date:
                item["baseline_date"] = inferred_date

        for platform, path in PLATFORM_PATHS.items():
            current = as_number(nested_get(item, path))
            previous = as_number(nested_get(prev or {}, path))
            change = pct_change(current, previous)
            platform_records[platform] = {
                "price": current,
                "previous_price": previous,
                "change_1d": round(change, 2) if change is not None else None,
            }
            if current is not None and change is not None:
                nested_set(item, path[:-1] + ("change_1d",), round(change, 2))
            if representative_change is None and change is not None and platform in ("xianyu_market", "aihuishou", "xianyu_official"):
                representative_change = change

        item["change_1d_by_platform"] = {
            key: value["change_1d"] for key, value in platform_records.items()
        }
        item["change_1d"] = round(representative_change, 2) if representative_change is not None else None

        records.append({
            "product_id": product_id,
            "product_name": item.get("product_name") or product_id,
            "updated_at": item.get("updated_at"),
            "platforms": platform_records,
            "representative_change_1d": item["change_1d"],
        })

    cache["updated_at"] = cache.get("updated_at") or now_iso()
    return {
        "version": "1.0.0",
        "date": scan_date,
        "generated_at": now_iso(),
        "source": str(PRICE_CACHE_FILE),
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--price-cache", default=str(PRICE_CACHE_FILE))
    parser.add_argument("--output-dir", default=str(DAILY_PRICE_DIR))
    args = parser.parse_args()

    cache_path = Path(args.price_cache)
    cache = load_json(cache_path)
    daily = build_daily_record(cache)
    output = Path(args.output_dir) / f"{daily['date']}.json"
    save_json(output, daily)
    if cache_path.resolve() == PRICE_CACHE_FILE.resolve():
        save_json(cache_path, cache)

    print(json.dumps({
        "ok": True,
        "output": str(output),
        "records": len(daily["records"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
