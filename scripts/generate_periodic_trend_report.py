#!/usr/bin/env python3
"""Generate weekly/monthly 7d/30d price trend report payload and PNG card."""
import argparse
import json
import math
import statistics
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
TREND_HISTORY_DIR = DATA_DIR / "trend_history"
OUTPUT_DIR = DATA_DIR / "periodic_reports"

WIDTH = 1080
HEIGHT = 1920
MARGIN = 64
FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]

PLATFORMS = {
    "xianyu_market": ("闲鱼自由市场", ("xianyu_market", "avg")),
    "xianyu_official": ("闲鱼官方回收", ("xianyu_official", "price")),
    "aihuishou": ("爱回收", ("aihuishou", "tansuo_price")),
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
    return ImageFont.load_default(size=size)


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
    for platform_key, (label, path) in PLATFORMS.items():
        values = []
        dates = []
        for item in history:
            data = item["data"]
            product_name = data.get("product_name") or data.get("model") or product_name
            value = as_number(nested_get(data, path))
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

    return {
        "version": "1.0.0",
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
            "status": "ok" if flat else "insufficient_data",
            "message": (
                f"近{config['label']}共分析{len(products)}个产品、{len(flat)}个平台价格序列。"
                if flat else f"近{config['label']}暂无可用历史价格，需先完成每日扫描和归档。"
            ),
        },
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
    xs = [92, 294, 430, 570, 710, 840]
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
    img = Image.new("RGBA", (WIDTH, HEIGHT), "#F7FAFC")
    draw = ImageDraw.Draw(img)
    draw_header(img, draw, payload)
    summary = payload["summary"]
    y = 330
    metric(draw, 64, y, 296, "产品数", summary["product_count"], "#155E75")
    metric(draw, 392, y, 296, "上涨序列", summary["rising"], "#047857")
    metric(draw, 720, y, 296, "下跌序列", summary["falling"], "#B42318")
    y += 168

    rounded(draw, (64, y, 1016, y + 174), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((96, y + 36), "趋势结论", font=font(31, True), fill="#164E63")
    draw.text((96, y + 94), summary["message"], font=font(34), fill="#111827")
    y += 214

    rounded(draw, (64, y, 1016, y + 900), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((96, y + 34), "波动排行", font=font(32, True), fill="#164E63")
    table_y = y + 104
    rounded(draw, (88, table_y - 38, 992, table_y + 18), radius=8, fill="#F1F5F9")
    draw_row(draw, table_y - 2, {}, header=True)
    table_y += 58
    for idx, item in enumerate(payload.get("top_movers") or []):
        if idx % 2 == 1:
            rounded(draw, (88, table_y - 34, 992, table_y + 12), radius=6, fill="#F8FAFC")
        draw_row(draw, table_y - 2, item)
        table_y += 58
        if table_y > y + 850:
            break
    if not payload.get("top_movers"):
        draw.text((96, table_y + 20), "暂无历史价格趋势数据", font=font(34), fill="#64748B")

    draw.text((64, 1848), "数据来源：data/trend_history｜周报/月报独立于每日播报", font=font(26), fill="#6D7788")
    img.convert("RGB").save(output_path, "PNG", optimize=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=sorted(PERIODS), required=True)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

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
