#!/usr/bin/env python3
"""Fetch structured market/news signals from TikHub.

The script reads credentials from environment variables only. It never prints
or persists the API key.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from http.client import RemoteDisconnected
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "tikhub_sources.json"
ENV_FILE = ROOT / ".env"
SENSITIVE_TEXT = re.compile(
    r"(Authorization[\"']?\s*[:=]\s*[\"']?Bearer\s+)[^\"',}\s]+",
    re.IGNORECASE,
)


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def redact_text(text: str) -> str:
    text = SENSITIVE_TEXT.sub(r"\1[REDACTED]", text)
    text = re.sub(r"(TIKHUB_API_KEY\s*=\s*)[^\s]+", r"\1[REDACTED]", text)
    return text


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_timestamp(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # TikHub platform APIs may return seconds or milliseconds.
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds)
        except (OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def first_value(obj, keys):
    if isinstance(obj, dict):
        for key in keys:
            if key in obj and obj[key] not in (None, ""):
                return obj[key]
    return None


def walk_dicts(value, limit=500):
    stack = [value]
    seen = 0
    while stack and seen < limit:
        item = stack.pop(0)
        seen += 1
        if isinstance(item, dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def candidate_records(payload):
    records = []
    for item in walk_dicts(payload):
        title = first_value(item, [
            "title", "desc", "description", "text", "content", "note_title",
            "share_title", "aweme_desc", "dynamic", "name",
        ])
        url = first_value(item, ["url", "share_url", "shareUrl", "web_url", "link", "uri"])
        published = first_value(item, [
            "published_at", "publish_time", "create_time", "ctime", "time",
            "created_at", "last_modify_ts", "date",
        ])
        author = first_value(item, [
            "nickname", "user_name", "author", "screen_name", "uname",
            "name", "display_name",
        ])
        if not title and not url:
            continue
        records.append({
            "title": str(title or "").strip()[:160],
            "url": str(url or "").strip(),
            "published_raw": published,
            "author": str(author or "").strip(),
            "raw": item,
        })
    return records


def build_url(base_url: str, endpoint: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")


def call_tikhub(base_url, api_key, source, query, timeout):
    url = build_url(base_url, source["endpoint"])
    method = str(source.get("method") or "GET").upper()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "zhuanzhuan-market-assistant/1.0",
    }
    params = dict(source.get("default_params") or {})
    params[source.get("query_param") or "keyword"] = query
    if method == "GET":
        from urllib.parse import urlencode

        separator = "&" if "?" in url else "?"
        request = Request(url + separator + urlencode(params), headers=headers, method="GET")
    else:
        body = json.dumps(params, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def format_http_error(exc: HTTPError) -> dict:
    body = ""
    try:
        body = redact_text(exc.read().decode("utf-8", errors="replace"))[:800]
    except Exception:
        body = ""
    return {
        "error": "HTTPError",
        "status": exc.code,
        "message": str(exc),
        "response_excerpt": body,
    }


def fix_platform_url(url: str, raw: dict, platform: str) -> str:
    """Convert deep-link or missing URLs to clickable web URLs."""
    if not url:
        # Try to construct from raw data
        if platform == "bilibili":
            bvid = first_value(raw, ["bvid", "BV"])
            aid = first_value(raw, ["aid", "avid"])
            if bvid and str(bvid).startswith("BV"):
                return f"https://www.bilibili.com/video/{bvid}"
            if aid:
                return f"https://www.bilibili.com/video/av{aid}"
        elif platform == "xiaohongshu":
            note_id = first_value(raw, ["note_id", "id", "noteId"])
            if note_id:
                return f"https://www.xiaohongshu.com/explore/{note_id}"
        return ""
    # B站: bilibili://video/12345 → https://www.bilibili.com/video/av12345
    if platform == "bilibili" and url.startswith("bilibili://video/"):
        bvid = first_value(raw, ["bvid", "BV"])
        aid_str = url.split("bilibili://video/")[1].split("?")[0]
        if bvid and str(bvid).startswith("BV"):
            return f"https://www.bilibili.com/video/{bvid}"
        if aid_str:
            return f"https://www.bilibili.com/video/av{aid_str}"
    # 抖音: aweme:// → 保留为空（无法转为web链接）
    if url.startswith("aweme://"):
        return ""
    return url


def normalize_item(record, source, query, max_age_days):
    pub_time = parse_timestamp(record.get("published_raw"))
    if pub_time is None:
        # Do not invent platform time. Use a low-confidence collection time so
        # the existing freshness filter can still mark it as recent but traceable.
        pub_time = datetime.now()
        time_quality = "collected_at_fallback"
    else:
        time_quality = "platform_publish_time"

    if pub_time < datetime.now() - timedelta(days=max_age_days):
        return None

    raw = record.get("raw") or {}
    url = fix_platform_url(record.get("url") or "", raw, source["platform"])
    domain = ""
    if url:
        domain = urlparse(url).netloc
    title = record.get("title") or f"{source['platform']} signal: {query}"
    return {
        "title": title,
        "summary": title,
        "source": f"tikhub:{source['platform']}",
        "platform": source["platform"],
        "source_id": source["id"],
        "query": query,
        "url": url,
        "domain": domain,
        "author": record.get("author") or "",
        "published_at": pub_time.strftime("%Y-%m-%d %H:%M:%S"),
        "publish_time_quality": time_quality,
        "level": source.get("level") or "B",
        "credibility": source.get("credibility_weight"),
        "raw": raw,
    }


def load_existing_items(output_path: Path):
    existing = load_json(output_path)
    if isinstance(existing, dict):
        return existing.get("items") or []
    if isinstance(existing, list):
        return existing
    return []


def dedupe_items(items):
    result = []
    seen = set()
    for item in items:
        key = item.get("url") or f"{item.get('source')}:{item.get('title')}:{item.get('published_at')}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(CONFIG_FILE))
    parser.add_argument("--output")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--source", action="append", help="Run only a source id. Can be repeated.")
    args = parser.parse_args()

    load_dotenv(ENV_FILE)
    config = load_json(Path(args.config))
    if not config.get("enabled", True):
        print(json.dumps({"ok": True, "skipped": "disabled"}, ensure_ascii=False, indent=2))
        return 0

    base_url = os.getenv(config.get("base_url_env") or "TIKHUB_BASE_URL", "https://api.tikhub.io")
    api_key = os.getenv(config.get("api_key_env") or "TIKHUB_API_KEY")
    if not api_key and not args.dry_run:
        raise SystemExit("Missing TIKHUB_API_KEY. Put it in .env or environment variables.")

    output_path = ROOT / (args.output or config.get("output") or "data/news_signals.json")
    timeout = int(config.get("timeout_seconds") or 20)
    max_items = int(config.get("max_items_per_source") or 8)
    max_age_days = int(config.get("max_age_days") or 7)
    selected = set(args.source or [])

    items = []
    errors = []
    calls = []
    for source in config.get("sources") or []:
        if not source.get("enabled", True):
            continue
        if selected and source.get("id") not in selected:
            continue
        source_items = []
        for query in source.get("queries") or []:
            calls.append({"source": source.get("id"), "platform": source.get("platform"), "query": query})
            if args.dry_run:
                continue
            try:
                payload = call_tikhub(base_url, api_key, source, query, timeout)
                for record in candidate_records(payload):
                    item = normalize_item(record, source, query, max_age_days)
                    if item:
                        source_items.append(item)
                    if len(source_items) >= max_items:
                        break
            except HTTPError as exc:
                errors.append({
                    "source": source.get("id"),
                    "platform": source.get("platform"),
                    "query": query,
                    **format_http_error(exc),
                })
            except (URLError, TimeoutError, RemoteDisconnected, json.JSONDecodeError) as exc:
                errors.append({
                    "source": source.get("id"),
                    "platform": source.get("platform"),
                    "query": query,
                    "error": type(exc).__name__,
                    "message": str(exc),
                })
            if len(source_items) >= max_items:
                break
            time.sleep(0.2)
        items.extend(source_items[:max_items])

    if args.append:
        items = load_existing_items(output_path) + items
    items = dedupe_items(items)
    result = {
        "version": "1.0.0",
        "generated_at": now_iso(),
        "source": "tikhub",
        "items": items,
        "errors": errors,
        "summary": {
            "calls": len(calls),
            "items": len(items),
            "errors": len(errors),
            "dry_run": bool(args.dry_run),
        },
    }
    if not args.dry_run:
        save_json(output_path, result)
    print(json.dumps({"ok": True, "output": str(output_path), **result["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
