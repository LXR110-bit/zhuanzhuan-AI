#!/usr/bin/env python3
"""Generate weekly/monthly 7d/30d price trend report payload and HTML-screenshot PNG card."""
import argparse
import html
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from render_cards_html import html_to_png


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TREND_HISTORY_DIR = DATA_DIR / "trend_history"
CATEGORIES_FILE = BASE_DIR / "config" / "categories.json"
BASELINE_FILE = BASE_DIR / "config" / "baseline.json"
ANOMALY_ARCHIVE_DIR = DATA_DIR / "anomaly_votes_archive"
OUTPUT_DIR = DATA_DIR / "periodic_reports"
TEMPLATE_FILE = BASE_DIR / "templates" / "periodic_trend_card.html"

WIDTH = 1080
HEIGHT = 1920

PLATFORMS = {
    "xianyu_market": (
        "闲鱼自由市场",
        (
            ("xianyu_market", "price"),
            ("xianyu_market", "median"),
            ("xianyu_market", "avg"),
            ("xianyu_market", "avg_price"),
        ),
    ),
    "xianyu_official": ("闲鱼官方回收", (("xianyu_official", "price"),)),
    "aihuishou": (
        "爱回收",
        (
            ("aihuishou", "tansuo_price"),
            ("aihuishou", "base_price"),
            ("aihuishou", "after_coupon"),
        ),
    ),
}

PERIODS = {
    "weekly": {"days": 7, "title": "价格趋势周报", "label": "7天"},
    "monthly": {"days": 30, "title": "价格趋势月报", "label": "30天"},
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
        value = as_number(nested_get(data, path))
        if value is not None:
            return value
    return None


def as_number(value):
    if value in (None, "", "-", "—"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def short_text(text, max_chars=14):
    text = str(text or "—")
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def fmt_price(value):
    if value is None:
        return "—"
    return f"¥{value:g}"


def fmt_pct(value):
    if value is None:
        return "—"
    return f"{value:+.1f}%"


def change_class(value):
    if value is None or abs(value) < 0.05:
        return "change-flat"
    return "change-up" if value > 0 else "change-down"


def escape(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def load_template(path=TEMPLATE_FILE):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def load_product_history(product_dir, days):
    rows = []
    for path in sorted(product_dir.glob("*.json"))[-days:]:
        raw = load_json(path)
        data = raw.get("data") or raw
        rows.append({"date": path.stem, "data": data})
    return rows


def slope(values):
    if len(values) < 2:
        return 0
    x = list(range(len(values)))
    xm = statistics.mean(x)
    ym = statistics.mean(values)
    denom = sum((i - xm) ** 2 for i in x)
    if denom == 0:
        return 0
    return sum((x[i] - xm) * (values[i] - ym) for i in x) / denom


def direction(change_pct, slope_value):
    if change_pct is None:
        return "数据不足"
    if abs(change_pct) < 1 and abs(slope_value) < 1:
        return "平稳"
    return "上涨" if change_pct > 0 or slope_value > 0 else "下跌"


def summarize_product(product_id, history):
    platform_rows = []
    product_name = product_id
    for platform_key, (label, paths) in PLATFORMS.items():
        values = []
        dates = []
        for item in history:
            data = item["data"]
            product_name = data.get("product_name") or data.get("model") or product_name
            value = nested_first(data, paths)
            if value is not None:
                values.append(value)
                dates.append(item["date"])
        if not values:
            continue
        current = values[-1]
        first = values[0]
        change_pct = ((current - first) / first * 100) if first else None
        slope_value = slope(values)
        platform_rows.append({
            "platform": platform_key,
            "platform_label": label,
            "current_price": round(current, 2),
            "first_price": round(first, 2),
            "start_date": dates[0],
            "end_date": dates[-1],
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "avg_price": round(statistics.mean(values), 2),
            "min_price": round(min(values), 2),
            "max_price": round(max(values), 2),
            "sample_count": len(values),
            "trend": direction(change_pct, slope_value),
        })
    return {
        "product_id": product_id,
        "product_name": product_name,
        "platforms": platform_rows,
    }


def build_category_trends(products, categories_file=CATEGORIES_FILE):
    """按品类聚合产品涨跌幅"""
    cat_data = load_json(categories_file) if categories_file.exists() else {}
    pid_to_cat = {}
    for cat_name, cat_info in (cat_data.get("categories") or {}).items():
        for item in cat_info.get("items", []):
            pid = item.get("id")
            if pid:
                pid_to_cat[pid] = cat_name

    agg = defaultdict(lambda: {"changes": [], "products": [], "count": 0})
    for product in products:
        pid = product["product_id"]
        cat = pid_to_cat.get(pid, "其他")
        agg[cat]["count"] += 1
        for plat in product.get("platforms", []):
            pct = plat.get("change_pct")
            if pct is not None:
                agg[cat]["changes"].append(pct)
                agg[cat]["products"].append({
                    "product_id": pid,
                    "product_name": product.get("product_name", pid),
                    "change_pct": pct,
                })

    result = []
    for cat, data in sorted(agg.items()):
        changes = data["changes"]
        avg_pct = round(statistics.mean(changes), 2) if changes else None
        if avg_pct is None:
            trend = "insufficient_data"
        elif abs(avg_pct) < 1:
            trend = "stable"
        elif avg_pct > 0:
            trend = "rising"
        else:
            trend = "falling"
        top = max(data["products"], key=lambda x: abs(x["change_pct"]), default=None) if data["products"] else None
        result.append({
            "category": cat,
            "avg_change_pct": avg_pct,
            "trend": trend,
            "product_count": data["count"],
            "top_mover": top,
        })
    return result


def build_anomaly_summary(period_days, archive_dir=ANOMALY_ARCHIVE_DIR):
    """读取异动归档，按产品聚合"""
    if not archive_dir.exists():
        return {"total_anomalies": 0, "by_level": {}, "items": []}

    cutoff = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
    all_items = []
    for f in sorted(archive_dir.glob("*.json")):
        if f.stem < cutoff:
            continue
        data = load_json(f)
        all_items.extend(data.get("items", []))

    if not all_items:
        return {"total_anomalies": 0, "by_level": {}, "items": []}

    by_level = defaultdict(int)
    by_product = defaultdict(lambda: {"count": 0, "levels": []})
    for item in all_items:
        lvl = item.get("level", "INFO")
        by_level[lvl] += 1
        pid = item.get("product_id", "unknown")
        by_product[pid]["count"] += 1
        by_product[pid]["levels"].append(lvl)
        by_product[pid]["product_name"] = item.get("product_name", pid)

    product_items = []
    for pid, info in sorted(by_product.items(), key=lambda x: x[1]["count"], reverse=True):
        levels = info["levels"]
        avg_level = max(set(levels), key=levels.count) if levels else "INFO"
        product_items.append({
            "product_id": pid,
            "product_name": info["product_name"],
            "anomaly_count": info["count"],
            "avg_level": avg_level,
        })

    return {
        "total_anomalies": len(all_items),
        "by_level": dict(by_level),
        "items": product_items[:10],
    }


def build_baseline_drift(products, baseline_file=BASELINE_FILE):
    """对比 baseline 与最近均价，找出漂移产品"""
    baseline = load_json(baseline_file) if baseline_file.exists() else {}
    baselines = baseline.get("baselines", {})
    if not baselines:
        return {"products_drifted": 0, "items": []}

    items = []
    for product in products:
        pid = product["product_id"]
        key = pid.replace("-", "_").replace(" ", "_")
        bl = baselines.get(key, {})
        bl_avg = bl.get("avg")
        if not isinstance(bl_avg, (int, float)) or not bl_avg:
            continue
        for plat in product.get("platforms", []):
            current_avg = plat.get("avg_price")
            if current_avg is None:
                continue
            drift_pct = round((current_avg - bl_avg) / bl_avg * 100, 2)
            if abs(drift_pct) > 10:
                items.append({
                    "product_id": pid,
                    "product_name": product.get("product_name", pid),
                    "baseline_avg": bl_avg,
                    "current_avg": current_avg,
                    "drift_pct": drift_pct,
                    "recommendation": "建议更新基准线" if abs(drift_pct) > 15 else "关注漂移",
                })
            break

    return {"products_drifted": len(items), "items": items}


def build_payload(period):
    config = PERIODS[period]
    products = []
    if TREND_HISTORY_DIR.exists():
        for product_dir in sorted(p for p in TREND_HISTORY_DIR.iterdir() if p.is_dir()):
            history = load_product_history(product_dir, config["days"])
            summary = summarize_product(product_dir.name, history)
            if summary["platforms"]:
                products.append(summary)

    flat = [
        {**platform, "product_id": product["product_id"], "product_name": product["product_name"]}
        for product in products
        for platform in product["platforms"]
    ]
    movers = sorted(flat, key=lambda item: abs(item.get("change_pct") or 0), reverse=True)[:12]
    rising = sum(1 for item in flat if (item.get("change_pct") or 0) > 0)
    falling = sum(1 for item in flat if (item.get("change_pct") or 0) < 0)
    stable = len(flat) - rising - falling

    category_trends = build_category_trends(products)
    anomaly_summary = build_anomaly_summary(config["days"])
    baseline_drift = build_baseline_drift(products)

    headline_parts = []
    for ct in category_trends:
        if ct["avg_change_pct"] is not None and abs(ct["avg_change_pct"]) >= 2:
            direction = "上涨" if ct["avg_change_pct"] > 0 else "下跌"
            headline_parts.append(f"{ct['category']}{direction}{abs(ct['avg_change_pct']):.1f}%")
    headline = "，".join(headline_parts[:3]) + "。" if headline_parts else "各品类整体平稳。"

    return {
        "version": "2.6.0",
        "period": period,
        "period_label": config["label"],
        "date": today_str(),
        "generated_at": now_iso(),
        "source": str(TREND_HISTORY_DIR),
        "summary": {
            "product_count": len(products),
            "platform_record_count": len(flat),
            "rising": rising,
            "falling": falling,
            "stable": stable,
            "status": "ok" if flat else "insufficient_data",
            "message": (
                f"近{config['label']}共分析{len(products)}个产品、{len(flat)}个平台价格序列。"
                if flat else f"近{config['label']}暂无可用历史价格，需先完成每日扫描和归档。"
            ),
            "headline": headline,
        },
        "category_trends": category_trends,
        "anomaly_summary": anomaly_summary,
        "baseline_drift": baseline_drift,
        "top_movers": movers,
        "products": products,
        "images": {},
    }


def trend_class(trend):
    return {
        "rising": "change-up",
        "falling": "change-down",
        "stable": "change-flat",
        "insufficient_data": "change-flat",
    }.get(trend, "change-flat")


def render_category_rows(payload):
    rows = []
    for item in payload.get("category_trends") or []:
        top = item.get("top_mover") or {}
        avg = item.get("avg_change_pct")
        rows.append(
            "<div class=\"category-row\">"
            f"<div class=\"category-name\">{escape(item.get('category') or '其他')}</div>"
            f"<div class=\"category-change {trend_class(item.get('trend'))}\">{fmt_pct(avg)}</div>"
            f"<div class=\"category-top\">最大波动：{escape(short_text(top.get('product_name') or '—', 18))} {escape(fmt_pct(top.get('change_pct')))}</div>"
            "</div>"
        )
    return "\n".join(rows) or "<div class=\"empty-state\">暂无品类趋势数据</div>"


def render_mover_rows(payload):
    movers = (payload.get("top_movers") or [])[:6]
    if not movers:
        return "<tr><td colspan=\"6\" class=\"empty-row\">暂无历史价格趋势数据</td></tr>"
    rows = []
    for item in movers:
        rows.append(
            "<tr>"
            f"<td class=\"product-name\">{escape(short_text(item.get('product_name'), 14))}</td>"
            f"<td>{escape(item.get('platform_label') or '—')}</td>"
            f"<td>{escape(fmt_price(item.get('current_price')))}</td>"
            f"<td>{escape(fmt_price(item.get('avg_price')))}</td>"
            f"<td class=\"{change_class(item.get('change_pct'))}\">{escape(fmt_pct(item.get('change_pct')))}</td>"
            f"<td>{escape(item.get('trend') or '—')}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def render_anomaly_block(payload):
    anomaly = payload.get("anomaly_summary") or {}
    if not anomaly.get("total_anomalies"):
        return ""
    rows = []
    for item in (anomaly.get("items") or [])[:5]:
        rows.append(
            "<div class=\"mini-row\">"
            f"<span>{escape(short_text(item.get('product_name'), 18))}</span>"
            f"<strong>{escape(item.get('anomaly_count'))}次</strong>"
            f"<em>主要级别：{escape(item.get('avg_level') or 'INFO')}</em>"
            "</div>"
        )
    return (
        "<section class=\"panel compact\">"
        f"<h2>异动汇总（共{escape(anomaly.get('total_anomalies'))}次）</h2>"
        f"{''.join(rows)}"
        "</section>"
    )


def render_drift_block(payload):
    drift = payload.get("baseline_drift") or {}
    if not drift.get("products_drifted"):
        return ""
    rows = []
    for item in (drift.get("items") or [])[:5]:
        rows.append(
            "<div class=\"mini-row\">"
            f"<span>{escape(short_text(item.get('product_name'), 18))}</span>"
            f"<strong class=\"{change_class(item.get('drift_pct'))}\">{escape(fmt_pct(item.get('drift_pct')))}</strong>"
            f"<em>{escape(item.get('recommendation') or '')}</em>"
            "</div>"
        )
    return (
        "<section class=\"panel compact\">"
        f"<h2>基准线漂移（{escape(drift.get('products_drifted'))}个产品）</h2>"
        f"{''.join(rows)}"
        "</section>"
    )


def render_html(payload, template_html):
    summary = payload["summary"]
    conclusion = summary.get("message") or ""
    if summary.get("headline"):
        conclusion = f"{conclusion} {summary['headline']}".strip()
    replacements = {
        "{{title}}": escape(PERIODS[payload["period"]]["title"]),
        "{{date}}": escape(payload.get("date")),
        "{{period_label}}": escape(payload.get("period_label")),
        "{{product_count}}": escape(summary.get("product_count", 0)),
        "{{rising}}": escape(summary.get("rising", 0)),
        "{{falling}}": escape(summary.get("falling", 0)),
        "{{stable}}": escape(summary.get("stable", 0)),
        "{{conclusion}}": escape(conclusion),
        "{{category_rows}}": render_category_rows(payload),
        "{{mover_rows}}": render_mover_rows(payload),
        "{{anomaly_block}}": render_anomaly_block(payload),
        "{{drift_block}}": render_drift_block(payload),
        "{{source}}": escape(payload.get("source") or "data/trend_history"),
    }
    rendered = template_html
    for key, value in replacements.items():
        rendered = rendered.replace(key, str(value))
    return rendered


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=sorted(PERIODS), required=True)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--template", default=str(TEMPLATE_FILE))
    parser.add_argument("--no-screenshot", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = build_payload(args.period)
    payload_path = output_dir / f"{payload['date']}_{args.period}_trend_payload.json"
    html_path = (output_dir / f"{payload['date']}_{args.period}_trend_card.html").resolve()
    image_path = (output_dir / f"{payload['date']}_{args.period}_trend_card.png").resolve()
    payload.setdefault("html", {})
    payload["html"]["trend_card"] = str(html_path)
    payload["images"]["trend_card"] = str(image_path)

    template_html = load_template(Path(args.template))
    card_html = render_html(payload, template_html)
    write_text(html_path, card_html)
    if not args.no_screenshot and not html_to_png(str(html_path), str(image_path), WIDTH, HEIGHT):
        raise SystemExit("截图失败：未能生成趋势报告 PNG")

    save_json(payload_path, payload)
    print(json.dumps({
        "ok": True,
        "period": args.period,
        "payload": str(payload_path.resolve()),
        "html": str(html_path),
        "trend_card": str(image_path),
        "status": payload["summary"]["status"],
        "products": payload["summary"]["product_count"],
        "render_engine": "html_css_browser_screenshot",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
