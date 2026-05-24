#!/usr/bin/env python3
"""Filter market/news signals before they enter the daily report.

Rules:
- Every kept item must carry a publish time.
- Items older than 7 days are dropped.
- Duplicate title/url keys within the 7-day history window are dropped.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

try:
    from signal_freshness import evaluate_signal_level
except ImportError:  # pragma: no cover - direct execution path handles this
    evaluate_signal_level = None


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
INPUT_FILE = DATA_DIR / "news_signals.json"
OUTPUT_FILE = DATA_DIR / "news_signals_filtered.json"
HISTORY_FILE = DATA_DIR / "news_signal_dedupe_history.json"
RELEVANCE_KEYWORDS = (
    "rtx", "nvidia", "英伟达", "显卡", "矿卡", "矿潮",
    "ddr", "dram", "nand", "ssd", "内存", "固态", "存储",
    "dji", "大疆", "pocket", "action", "mini", "无人机",
    "insta360", "影石", "gopro", "运动相机", "拇指相机",
    "13600k", "13700k", "5600x", "5800x3d", "cpu",
    "小米手环", "智能手环", "手环",
    "爱回收", "回收价", "二手价格", "以旧换新",
)
IRRELEVANT_KEYWORDS = (
    "废旧手机", "旧手机", "手机回收", "折叠屏手机", "iphone",
    "华强北手机", "碰撞概率", "概率碰撞", "至少碰撞", "无套路",
)


def now():
    return datetime.now()


def now_iso():
    return now().isoformat()


def today_str():
    return now().strftime("%Y-%m-%d")


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


def parse_time(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    if text.endswith("Z"):
        try:
            return datetime.fromisoformat(text[:-1]).replace(tzinfo=None)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def normalize_title(title):
    text = re.sub(r"\s+", "", str(title or "")).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text)
    return text


def dedupe_key(item):
    url = item.get("url") or item.get("source_url")
    if url:
        return f"url:{url}"
    title = normalize_title(item.get("title") or item.get("summary"))
    source = item.get("source") or ""
    raw = f"{source}:{title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def publish_time(item):
    return (
        item.get("published_at")
        or item.get("publish_time")
        or item.get("publish_date")
        or item.get("event_date")
    )


def signal_url(item):
    return item.get("url") or item.get("source_url") or item.get("link") or ""


def valid_http_url(value):
    if not value:
        return False
    parsed = urlparse(str(value))
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def meaningful_title(value):
    title = str(value or "").strip()
    generic = {"无标题", "未命名信号", "大家都在搜", "相关搜索"}
    if not title or title in generic:
        return False
    if re.fullmatch(r"(\d+\s*(分钟前|小时前|天前)|昨天\s*\d{1,2}:\d{2}|前天\s*\d{1,2}:\d{2})", title):
        return False
    if len(normalize_title(title)) < 4:
        return False
    return True


def market_relevant(item):
    text = " ".join(str(item.get(key) or "") for key in ("title", "summary", "description", "content", "query"))
    text_lower = text.lower()
    if any(word.lower() in text_lower for word in IRRELEVANT_KEYWORDS):
        return False
    return any(word.lower() in text_lower for word in RELEVANCE_KEYWORDS)


def load_history(path, max_age_days=7):
    raw = load_json(path)
    cutoff = now() - timedelta(days=max_age_days)
    entries = {}
    for key, entry in (raw.get("entries") or {}).items():
        first_seen = parse_time(entry.get("first_seen_at"))
        last_published = parse_time(entry.get("published_at"))
        reference_time = first_seen or last_published
        if reference_time and reference_time >= cutoff:
            entries[key] = entry
    return {
        "version": "1.0.0",
        "updated_at": now_iso(),
        "window_days": max_age_days,
        "entries": entries,
    }


def remember(history, item, key, pub_time):
    entries = history.setdefault("entries", {})
    if key not in entries:
        entries[key] = {
            "first_seen_at": now_iso(),
            "published_at": pub_time.strftime("%Y-%m-%d %H:%M:%S"),
            "publish_date": pub_time.strftime("%Y-%m-%d"),
            "title": item.get("title") or item.get("summary") or "",
            "source": item.get("source") or "",
            "url": item.get("url") or item.get("source_url") or "",
            "count": 0,
        }
    entries[key]["last_seen_at"] = now_iso()
    entries[key]["count"] = int(entries[key].get("count", 0)) + 1
    return history


def filter_signals(data, max_age_days=7, history=None):
    cutoff = now() - timedelta(days=max_age_days)
    kept = []
    dropped = []
    history = history or {"entries": {}}
    seen = set(history.get("entries", {}).keys())
    current_batch = set()
    items = data.get("items") if isinstance(data, dict) else data
    items = items or []

    for item in items:
        if not isinstance(item, dict):
            dropped.append({"reason": "invalid_item", "raw": item})
            continue
        if item.get("publish_time_quality") and item.get("publish_time_quality") != "platform_publish_time":
            dropped.append({"reason": "invalid_publish_time_quality", "item": item})
            continue
        if not meaningful_title(item.get("title") or item.get("summary")):
            dropped.append({"reason": "invalid_or_generic_title", "item": item})
            continue
        if not valid_http_url(signal_url(item)):
            dropped.append({"reason": "missing_valid_url", "item": item})
            continue
        if not market_relevant(item):
            dropped.append({"reason": "irrelevant_to_monitored_categories", "item": item})
            continue
        pub_raw = publish_time(item)
        pub_time = parse_time(pub_raw)
        if pub_time is None:
            dropped.append({"reason": "missing_publish_time", "item": item})
            continue
        if pub_time < cutoff:
            dropped.append({"reason": "older_than_7_days", "published_at": pub_raw, "item": item})
            continue

        key = dedupe_key(item)
        if key in current_batch:
            dropped.append({"reason": "duplicate_in_current_batch", "dedupe_key": key, "item": item})
            continue
        if key in seen:
            dropped.append({"reason": "duplicate_in_7_day_history", "dedupe_key": key, "item": item})
            continue
        current_batch.add(key)

        base_level = str(item.get("level") or item.get("base_level") or "B").replace("级", "")
        adjusted_level = base_level
        if evaluate_signal_level:
            adjusted_level = evaluate_signal_level(pub_time.strftime("%Y-%m-%d"), base_level)

        kept_item = dict(item)
        kept_item["published_at"] = pub_time.strftime("%Y-%m-%d %H:%M:%S")
        kept_item["publish_date"] = pub_time.strftime("%Y-%m-%d")
        kept_item["age_days"] = (now() - pub_time).days
        kept_item["dedupe_key"] = key
        kept_item["level"] = adjusted_level
        kept.append(kept_item)
        remember(history, kept_item, key, pub_time)

    return {
        "version": "1.0.0",
        "date": today_str(),
        "generated_at": now_iso(),
        "max_age_days": max_age_days,
        "items": kept,
        "dropped": dropped,
        "summary": {
            "input": len(items),
            "kept": len(kept),
            "dropped": len(dropped),
            "history_size": len(history.get("entries", {})),
        },
    }, history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(INPUT_FILE))
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    parser.add_argument("--history", default=str(HISTORY_FILE))
    parser.add_argument("--max-age-days", type=int, default=7)
    args = parser.parse_args()

    data = load_json(Path(args.input))
    history = load_history(Path(args.history), max_age_days=args.max_age_days)
    result, history = filter_signals(data, max_age_days=args.max_age_days, history=history)
    save_json(Path(args.output), result)
    save_json(Path(args.history), history)
    print(json.dumps({
        "ok": True,
        "input": str(args.input),
        "output": str(args.output),
        "history": str(args.history),
        **result["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
