#!/usr/bin/env python3
"""Generate weekly/monthly 7d/30d price trend report payload and PNG card. v2.6"""
import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TREND_HISTORY_DIR = DATA_DIR / "trend_history"
CATEGORIES_FILE = BASE_DIR / "config" / "categories.json"
BASELINE_FILE = BASE_DIR / "config" / "baseline.json"
ANOMALY_ARCHIVE_DIR = DATA_DIR / "anomaly_votes_archive"
OUTPUT_DIR = DATA_DIR / "periodic_reports"

WIDTH = 1080
HEIGHT = 1920
MARGIN = 64
FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]

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


def font(size, bold=False):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size, index=1 if bold and path.endswith(".ttc") else 0)
            except OSError:
                continue
    raise RuntimeError(
        "No CJK-capable font found for trend card rendering; install a Chinese font "
        "or add its path to FONT_CANDIDATES."
    )


def assert_cjk_font_available():
    probe_font = font(32, True)
    mask = probe_font.getmask("价格趋势周报")
    if mask.getbbox() is None:
        raise RuntimeError("Selected font cannot render Chinese trend card text.")


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def gradient(size, left, right):
    w, h = size
    img = Image.new("RGB", size, left)
    draw = ImageDraw.Draw(img)
    l = hex_rgb(left)
    r = hex_rgb(right)
    for x in range(w):
        t = x / max(w - 1, 1)
        color = tuple(int(l[i] * (1 - t) + r[i] * t) for i in range(3))
        draw.line((x, 0, x, h), fill=color)
    return img


def rounded(draw, xy, radius=8, fill="#FFFFFF", outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), str(text), font=fnt)
    return box[2] - box[0], box[3] - box[1]


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


def change_color(value):
    if value is None:
        return "#475569"
    return "#047857" if value > 0 else "#B42318" if value < 0 else "#475569"


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


def draw_header(img, draw, payload):
    band = gradient((WIDTH, 350), "#164E63", "#7C3AED").convert("RGBA")
    mask = Image.new("L", (WIDTH, 350), 0)
    md = ImageDraw.Draw(mask)
    md.polygon([(0, 0), (WIDTH, 0), (WIDTH, 286), (850, 318), (580, 292), (300, 334), (0, 304)], fill=255)
    img.alpha_composite(Image.composite(band, Image.new("RGBA", band.size, (0, 0, 0, 0)), mask), (0, 0))
    title = PERIODS[payload["period"]]["title"]
    draw.text((MARGIN, 84), title, font=font(62, True), fill="#FFFFFF")
    draw.text((MARGIN + 2, 158), f"{payload['date']} | 周期 {payload['period_label']}", font=font(30), fill="#E0F2FE")


def metric(draw, x, y, w, label, value, accent):
    rounded(draw, (x, y, x + w, y + 124), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((x + 24, y + 28), label, font=font(27, True), fill="#64748B")
    draw.text((x + 24, y + 72), str(value), font=font(44, True), fill=accent)


def draw_row(draw, y, item, header=False):
    xs = [92, 310, 470, 610, 750, 880]
    if header:
        values = ["产品", "平台", "当前", "均值", "涨跌", "趋势"]
    else:
        values = [
            short_text(item.get("product_name"), 12),
            item.get("platform_label"),
            fmt_price(item.get("current_price")),
            fmt_price(item.get("avg_price")),
            fmt_pct(item.get("change_pct")),
            item.get("trend"),
        ]
    for idx, value in enumerate(values):
        color = "#243044"
        if idx == 4 and not header:
            color = change_color(item.get("change_pct"))
        draw.text((xs[idx], y), str(value), font=font(26, header or idx == 4), fill=color)


def render_card(payload, output_path):
    summary = payload["summary"]
    movers = payload.get("top_movers") or []
    cat_trends = payload.get("category_trends") or []
    anomaly = payload.get("anomaly_summary") or {}
    drift = payload.get("baseline_drift") or {}

    # 动态计算高度
    base_h = 750
    table_h = max(len(movers), 1) * 58 + 120
    cat_h = (len(cat_trends) * 48 + 100) if cat_trends else 0
    anomaly_h = (min(len(anomaly.get("items", [])), 5) * 48 + 100) if anomaly.get("total_anomalies") else 0
    drift_h = (len(drift.get("items", [])) * 48 + 100) if drift.get("products_drifted") else 0
    total_h = base_h + table_h + cat_h + anomaly_h + drift_h + 80

    img = Image.new("RGBA", (WIDTH, total_h), "#F7FAFC")
    draw = ImageDraw.Draw(img)
    draw_header(img, draw, payload)

    y = 330
    metric(draw, 64, y, 220, "产品数", summary["product_count"], "#155E75")
    metric(draw, 310, y, 220, "上涨", summary["rising"], "#047857")
    metric(draw, 556, y, 220, "下跌", summary["falling"], "#B42318")
    metric(draw, 802, y, 220, "平稳", summary.get("stable", 0), "#475569")
    y += 168

    # 趋势结论 + headline
    headline = summary.get("headline", "")
    conclusion_text = summary["message"] + (" " + headline if headline else "")
    rounded(draw, (64, y, 1016, y + 174), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((96, y + 36), "趋势结论", font=font(31, True), fill="#164E63")
    draw.text((96, y + 94), conclusion_text[:50], font=font(30), fill="#111827")
    y += 214

    # 品类趋势区块
    if cat_trends:
        block_h = len(cat_trends) * 48 + 80
        rounded(draw, (64, y, 1016, y + block_h), radius=8, fill="#FFFFFF", outline="#E2E8F0")
        draw.text((96, y + 28), "品类趋势", font=font(31, True), fill="#164E63")
        cy = y + 80
        for ct in cat_trends:
            cat_name = ct["category"]
            avg_pct = ct.get("avg_change_pct")
            trend = ct.get("trend", "")
            arrow = "↑" if trend == "rising" else ("↓" if trend == "falling" else "→")
            color = "#047857" if trend == "rising" else ("#B42318" if trend == "falling" else "#475569")
            pct_str = f"{avg_pct:+.1f}%" if avg_pct is not None else "—"
            draw.text((96, cy), f"{cat_name}", font=font(27, True), fill="#243044")
            draw.text((320, cy), f"{arrow} {pct_str}", font=font(27, True), fill=color)
            top = ct.get("top_mover")
            if top:
                draw.text((520, cy), f"最大波动: {top['product_name']} {top['change_pct']:+.1f}%", font=font(24), fill="#64748B")
            cy += 48
        y += block_h + 20

    # 波动排行
    table_block_h = max(len(movers), 1) * 58 + 100
    rounded(draw, (64, y, 1016, y + table_block_h), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((96, y + 34), "波动排行", font=font(32, True), fill="#164E63")
    table_y = y + 104
    rounded(draw, (88, table_y - 38, 992, table_y + 18), radius=8, fill="#F1F5F9")
    draw_row(draw, table_y - 2, {}, header=True)
    table_y += 58
    for idx, item in enumerate(movers):
        if idx % 2 == 1:
            rounded(draw, (88, table_y - 34, 992, table_y + 12), radius=6, fill="#F8FAFC")
        draw_row(draw, table_y - 2, item)
        table_y += 58
        if idx >= 11:
            break
    if not movers:
        draw.text((96, table_y + 20), "暂无历史价格趋势数据", font=font(34), fill="#64748B")
    y += table_block_h + 20

    # 异动汇总区块
    anomaly_items = anomaly.get("items", [])[:5]
    if anomaly.get("total_anomalies"):
        block_h = len(anomaly_items) * 48 + 80
        rounded(draw, (64, y, 1016, y + block_h), radius=8, fill="#FFFFFF", outline="#E2E8F0")
        draw.text((96, y + 28), f"异动汇总（共{anomaly['total_anomalies']}次）", font=font(31, True), fill="#164E63")
        ay = y + 80
        for ai in anomaly_items:
            lvl_color = {"CRITICAL": "#B42318", "ALERT": "#D97706", "S": "#B42318", "A": "#D97706"}.get(ai.get("avg_level"), "#475569")
            draw.text((96, ay), f"{ai['product_name']}", font=font(27, True), fill="#243044")
            draw.text((420, ay), f"{ai['anomaly_count']}次", font=font(27), fill=lvl_color)
            draw.text((520, ay), f"主要级别: {ai['avg_level']}", font=font(24), fill="#64748B")
            ay += 48
        y += block_h + 20

    # Baseline 漂移区块
    drift_items = drift.get("items", [])
    if drift.get("products_drifted"):
        block_h = len(drift_items) * 48 + 80
        rounded(draw, (64, y, 1016, y + block_h), radius=8, fill="#FFFFFF", outline="#E2E8F0")
        draw.text((96, y + 28), f"基准线漂移（{drift['products_drifted']}个产品）", font=font(31, True), fill="#164E63")
        dy = y + 80
        for di in drift_items:
            drift_color = "#B42318" if di["drift_pct"] < 0 else "#047857"
            draw.text((96, dy), f"{di['product_name']}", font=font(27, True), fill="#243044")
            draw.text((420, dy), f"{di['drift_pct']:+.1f}%", font=font(27, True), fill=drift_color)
            draw.text((520, dy), di.get("recommendation", ""), font=font(24), fill="#64748B")
            dy += 48
        y += block_h + 20

    draw.text((64, total_h - 52), "数据来源：data/trend_history｜周报/月报独立于每日播报", font=font(26), fill="#6D7788")
    img.convert("RGB").save(output_path, "PNG", optimize=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=sorted(PERIODS), required=True)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    assert_cjk_font_available()
    output_dir = Path(args.output_dir)
    payload = build_payload(args.period)
    payload_path = output_dir / f"{payload['date']}_{args.period}_trend_payload.json"
    image_path = (output_dir / f"{payload['date']}_{args.period}_trend_card.png").resolve()
    payload["images"]["trend_card"] = str(image_path)
    save_json(payload_path, payload)
    render_card(payload, image_path)
    print(json.dumps({
        "ok": True,
        "period": args.period,
        "payload": str(payload_path.resolve()),
        "trend_card": str(image_path),
        "status": payload["summary"]["status"],
        "products": payload["summary"]["product_count"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
