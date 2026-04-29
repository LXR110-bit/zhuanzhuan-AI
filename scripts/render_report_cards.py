#!/usr/bin/env python3
"""Render daily report payload into two PNG image cards."""
import argparse
import json
import math
import textwrap
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE_DIR = Path(__file__).resolve().parent.parent
PAYLOAD_FILE = BASE_DIR / "data" / "daily_report_payload.json"
PUSH_STATUS_FILE = BASE_DIR / "data" / "push_status.json"
OUTPUT_DIR = BASE_DIR / "data" / "report_cards"

WIDTH = 1080
HEIGHT = 1920
MARGIN = 64

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]


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


def validate_payload(payload):
    errors = []
    summary = payload.get("summary", {})
    if not payload.get("date"):
        errors.append("payload.date is required")
    if not summary.get("one_sentence"):
        errors.append("payload.summary.one_sentence is required")
    if not summary.get("today_action"):
        errors.append("payload.summary.today_action is required")
    return errors


def font(size, bold=False):
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size, index=1 if bold and path.endswith(".ttc") else 0)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def palette(kind):
    if kind == "market":
        return {
            "page": "#F6F8FB",
            "accent": "#155E75",
            "accent_2": "#4338CA",
            "soft": "#E0F2FE",
            "ink": "#111827",
            "muted": "#64748B",
        }
    return {
        "page": "#F7FAF9",
        "accent": "#0F766E",
        "accent_2": "#1D4ED8",
        "soft": "#CCFBF1",
        "ink": "#111827",
        "muted": "#64748B",
    }


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
        draw.line([(x, 0), (x, h)], fill=color)
    return img


def rounded(draw, xy, radius=8, fill="#FFFFFF", outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def text_size(draw, text, fnt):
    box = draw.textbbox((0, 0), str(text), font=fnt)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(text, chars=24, max_lines=3):
    text = str(text or "无")
    lines = []
    for part in text.splitlines() or ["无"]:
        lines.extend(textwrap.wrap(part, width=chars, break_long_words=True) or [""])
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(0, chars - 1)] + "…"
    return lines


def draw_wrapped(draw, xy, text, fnt, fill="#111827", chars=24, line_gap=12, max_lines=3):
    x, y = xy
    for line in wrap_text(text, chars=chars, max_lines=max_lines):
        draw.text((x, y), line, font=fnt, fill=fill)
        _, h = text_size(draw, line, fnt)
        y += h + line_gap
    return y


def short_text(text, max_chars=16):
    text = str(text or "—")
    return text if len(text) <= max_chars else text[: max_chars - 1] + "…"


def change_color(value):
    value = str(value or "")
    if value.startswith("+") or "↑" in value:
        return "#047857"
    if value.startswith("-") or "↓" in value:
        return "#B42318"
    return "#475569"


def header(img, draw, title, subtitle, kind):
    colors = palette(kind)
    band = gradient((WIDTH, 360), colors["accent"], colors["accent_2"]).convert("RGBA")
    mask = Image.new("L", (WIDTH, 360), 0)
    md = ImageDraw.Draw(mask)
    points = [
        (0, 0), (WIDTH, 0), (WIDTH, 288), (920, 318), (720, 300),
        (520, 340), (320, 300), (150, 312), (0, 350),
    ]
    md.polygon(points, fill=255)
    shaped_band = Image.composite(band, Image.new("RGBA", band.size, (0, 0, 0, 0)), mask)
    img.alpha_composite(shaped_band, (0, 0))

    for x in range(760, 1013, 64):
        draw.line((x, 42, x, 236), fill=(255, 255, 255, 36), width=2)
    for y in range(60, 230, 48):
        draw.line((760, y, 1012, y), fill=(255, 255, 255, 36), width=2)

    draw.text((MARGIN, 82), title, font=font(60, True), fill="#FFFFFF")
    draw.text((MARGIN + 2, 154), subtitle, font=font(29), fill="#E0F2FE")


def metric(draw, x, y, w, label, value, accent):
    rounded(draw, (x, y, x + w, y + 124), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((x + 26, y + 28), label, font=font(27, True), fill="#64748B")
    draw.text((x + 26, y + 74), value, font=font(44, True), fill=accent)


def signal_text(item):
    if isinstance(item, dict):
        title = item.get("title") or str(item)
        publish_date = item.get("publish_date")
        if not publish_date and item.get("published_at"):
            publish_date = str(item.get("published_at"))[:10]
        return f"{publish_date}｜{title}" if publish_date else title
    return str(item)


def draw_signal_panel(draw, x, y, title, items, accent, fill):
    rounded(draw, (x, y, x + 952, y + 220), radius=8, fill=fill, outline="#E2E8F0")
    draw.rounded_rectangle((x, y, x + 8, y + 220), radius=4, fill=accent)
    draw.text((x + 32, y + 34), title, font=font(30, True), fill=accent)
    lines = [signal_text(item) for item in (items or [])[:3]] or ["无"]
    line_y = y + 92
    for line in lines:
        line_y = draw_wrapped(draw, (x + 36, line_y), line, font(28), fill="#334155", chars=34, line_gap=4, max_lines=2)
        line_y += 22


def render_market_card(payload, output_path):
    colors = palette("market")
    img = Image.new("RGBA", (WIDTH, HEIGHT), colors["page"])
    draw = ImageDraw.Draw(img)
    summary = payload.get("summary", {})
    signals = payload.get("signals", {})
    risks = payload.get("risks", {})
    date = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    generated_at = payload.get("generated_at") or "未生成"

    header(img, draw, "市场追踪日报", f"{date} | 更新 {generated_at}", "market")
    y = 330
    signal_total = sum(len(signals.get(k) or []) for k in ("S", "A", "B"))
    missing = risks.get("missing_data") or []
    metric(draw, 64, y, 296, "S级信号", str(len(signals.get("S") or [])), "#B42318")
    metric(draw, 392, y, 296, "关注信号", str(signal_total), "#C2410C")
    metric(draw, 720, y, 296, "缺失项", str(len(missing)), "#475569")
    y += 168

    rounded(draw, (64, y, 1016, y + 214), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((96, y + 38), "今日结论", font=font(30, True), fill=colors["accent"])
    draw_wrapped(draw, (96, y + 98), summary.get("one_sentence"), font(42, True), fill=colors["ink"], chars=29, line_gap=12, max_lines=2)
    y += 246

    rounded(draw, (64, y, 1016, y + 184), radius=8, fill="#ECFDF5", outline="#BBF7D0")
    draw.text((96, y + 34), "今日动作", font=font(30, True), fill="#047857")
    draw_wrapped(draw, (96, y + 90), summary.get("today_action"), font(34), fill="#163B2C", chars=32, line_gap=8, max_lines=2)
    y += 222

    for title, level, accent, fill in (
        ("S级信号", "S", "#B42318", "#FEF2F2"),
        ("A级信号", "A", "#C2410C", "#FFF7ED"),
        ("B级观察", "B", "#2563EB", "#EFF6FF"),
    ):
        draw_signal_panel(draw, 64, y, title, signals.get(level) or [], accent, fill)
        y += 248

    rounded(draw, (64, y, 1016, y + 126), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((96, y + 34), "数据质量", font=font(29, True), fill="#475569")
    draw_wrapped(draw, (96, y + 82), summary.get("data_quality") or "正常", font(27), fill="#475569", chars=39, line_gap=4, max_lines=2)
    draw.text((64, 1888), "数据来源：统一日报 payload｜行情仅展示7天内去重内容", font=font(26), fill="#6D7788")

    img.convert("RGB").save(output_path, "PNG", optimize=True)


def price_row(draw, y, row, header_row=False):
    values = [
        short_text(row.get("model") or row.get("机型") or "-", 13),
        short_text(row.get("xianyu_market") or row.get("闲鱼市场") or "-", 9),
        short_text(row.get("xianyu_recycle") or row.get("闲鱼回收") or "-", 9),
        short_text(row.get("aihuishou") or row.get("爱回收") or "-", 9),
        short_text(row.get("daily_change") or row.get("日环比") or "-", 8),
    ]
    xs = [96, 330, 520, 700, 880]
    for idx, (x, value) in enumerate(zip(xs, values)):
        color = change_color(value) if idx == 4 and not header_row else "#243044"
        draw.text((x, y), value, font=font(27, True if header_row or idx == 4 else False), fill=color)


def render_price_card(payload, output_path):
    colors = palette("price")
    img = Image.new("RGBA", (WIDTH, HEIGHT), colors["page"])
    draw = ImageDraw.Draw(img)
    prices = payload.get("prices", {})
    risks = payload.get("risks", {})
    date = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    updated_at = prices.get("updated_at") or "未更新"
    rows = prices.get("rows") or []
    alert_count = len(risks.get("drop_alerts") or []) + len(risks.get("rise_alerts") or [])

    header(img, draw, "价格监控日报", f"{date} | 价格更新 {updated_at}", "price")
    y = 330
    complete = "0%"
    if rows:
        available = sum(
            1 for row in rows
            if (row.get("xianyu_market") or row.get("xianyu_recycle") or row.get("aihuishou")) not in ("", "-", "—", None)
        )
        complete = f"{round(available / len(rows) * 100)}%"
    metric(draw, 64, y, 296, "价格记录", str(len(rows)), "#0F766E")
    metric(draw, 392, y, 296, "完成率", complete, "#1D4ED8")
    metric(draw, 720, y, 296, "异动数", str(alert_count), "#B45309")
    y += 168

    rounded(draw, (64, y, 1016, y + 700), radius=8, fill="#FFFFFF", outline="#E2E8F0")
    draw.text((96, y + 34), "价格总览", font=font(32, True), fill=colors["accent"])
    table_y = y + 102
    rounded(draw, (88, table_y - 38, 992, table_y + 18), radius=8, fill="#F1F5F9")
    price_row(draw, table_y - 2, {"model": "机型", "xianyu_market": "自由市", "xianyu_recycle": "官方回", "aihuishou": "爱回收", "daily_change": "日环比"}, True)
    table_y += 58
    for idx, row in enumerate(rows[:10]):
        if idx % 2 == 1:
            rounded(draw, (88, table_y - 36, 992, table_y + 12), radius=6, fill="#F8FAFC")
        price_row(draw, table_y - 2, row if isinstance(row, dict) else {"model": row})
        table_y += 52
    if not rows:
        draw.text((96, table_y), "暂无价格数据", font=font(32), fill="#64748B")
    y += 748

    for x, title, items, accent, fill in (
        (64, "下跌预警", risks.get("drop_alerts") or [], "#B42318", "#FEF2F2"),
        (552, "上涨提示", risks.get("rise_alerts") or [], "#047857", "#ECFDF5"),
    ):
        rounded(draw, (x, y, x + 464, y + 300), radius=8, fill=fill, outline="#E2E8F0")
        draw.text((x + 30, y + 34), title, font=font(30, True), fill=accent)
        line_y = y + 104
        if not items:
            draw.text((x + 30, line_y), "无", font=font(30), fill="#64748B")
        else:
            for item in items[:3]:
                line_y = draw_wrapped(draw, (x + 30, line_y), item, font(27), fill="#334155", chars=16, line_gap=4, max_lines=2)
                line_y += 26

    draw.text((64, 1848), "数据来源：闲鱼自由市场价格 / 闲鱼官方回收价格 / 爱回收价格｜仅展示价格与日环比", font=font(26), fill="#6D7788")
    img.convert("RGB").save(output_path, "PNG", optimize=True)


def update_payload_and_status(payload_path, payload, market_path, price_path):
    payload.setdefault("images", {})
    payload["images"]["market_daily_card"] = str(market_path)
    payload["images"]["price_monitor_card"] = str(price_path)
    payload["generated_at"] = payload.get("generated_at") or datetime.now().isoformat()
    save_json(payload_path, payload)

    if payload_path.resolve() != PAYLOAD_FILE.resolve():
        return

    status = load_json(PUSH_STATUS_FILE)
    if status:
        status["date"] = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
        status["updated_at"] = datetime.now().isoformat()
        daily = status.setdefault("daily_report", {})
        if daily.get("status") not in ("sent", "missed"):
            daily["status"] = "image_ready"
        daily["image_required"] = True
        daily.setdefault("images", {})
        daily["images"]["market_daily_card"] = str(market_path)
        daily["images"]["price_monitor_card"] = str(price_path)
        if daily.get("status") not in ("sent", "missed"):
            daily["last_error"] = None
        save_json(PUSH_STATUS_FILE, status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", default=str(PAYLOAD_FILE))
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()

    payload_path = Path(args.payload)
    payload = load_json(payload_path)
    if not payload:
        raise SystemExit(f"payload not found or empty: {payload_path}")
    errors = validate_payload(payload)
    if errors:
        raise SystemExit("; ".join(errors))

    date = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    market_path = (output_dir / f"{date}_market_daily_card.png").resolve()
    price_path = (output_dir / f"{date}_price_monitor_card.png").resolve()

    render_market_card(payload, market_path)
    render_price_card(payload, price_path)
    update_payload_and_status(payload_path.resolve(), payload, market_path, price_path)

    print(json.dumps({
        "ok": True,
        "market_daily_card": str(market_path),
        "price_monitor_card": str(price_path),
        "format": "png",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
