#!/usr/bin/env python3
"""Send generated daily report cards.

Preferred mode:
- Set WECOM_WEBHOOK_URL
- Set REPORT_CARD_BASE_URL pointing to a public/static directory that exposes
  files in data/report_cards/

Fallback mode:
- If REPORT_CARD_BASE_URL is not set, upload the combined PNG as a WeCom bot file.
"""
import argparse
import json
import mimetypes
import os
import subprocess
import sys
import uuid
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from report_guard import check_before_push
from runtime_logger import log_event, log_exception


BASE_DIR = Path(__file__).resolve().parent.parent
PRICE_CACHE_FILE = BASE_DIR / "data" / "price_cache.json"
PAYLOAD_FILE = BASE_DIR / "data" / "daily_report_payload.json"
PUSH_STATUS_FILE = BASE_DIR / "data" / "push_status.json"
OUTBOX_DIR = BASE_DIR / "data" / "outbox"
REPAIR_LOG_FILE = BASE_DIR / "data" / "logs" / "daily_report_pipeline.log"
PRICE_COLLECTION_FLAG = BASE_DIR / "data" / "price_collection_done.flag"
REPAIR_COMMANDS = [
    [sys.executable, "scripts/price_data_validator.py"],
    [sys.executable, "scripts/price_daily_recorder.py"],
    [sys.executable, "scripts/generate_daily_report_payload.py"],
    [sys.executable, "scripts/render_cards_html.py"],
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


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def is_weekday():
    return datetime.now().weekday() < 5


def log_repair(message):
    REPAIR_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REPAIR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} {message}\n")
    log_event("daily_report.repair_log", message=message)


def file_is_today(path):
    path = Path(path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return False
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d") == today_str()


def flag_is_today(path):
    path = Path(path)
    if not path.exists():
        return False
    try:
        payload = load_json(path)
    except (json.JSONDecodeError, OSError):
        payload = {}
    return payload.get("date") == today_str() or file_is_today(path)


def json_data_is_today(path):
    data = load_json(path)
    if not data:
        return False
    if data.get("date") == today_str():
        return True
    for key in ("updated_at", "generated_at", "scan_time"):
        value = str(data.get(key) or "")
        if value.startswith(today_str()):
            return True
    return file_is_today(path)


def needs_report_repair():
    payload = load_json(PAYLOAD_FILE)
    status = load_json(PUSH_STATUS_FILE)
    reasons = []

    if not json_data_is_today(PRICE_CACHE_FILE):
        reasons.append("price_cache missing_or_stale")
    if payload.get("date") != today_str():
        reasons.append(f"payload.date={payload.get('date')}")
    if status.get("date") != today_str():
        reasons.append(f"push_status.date={status.get('date')}")
    if not flag_is_today(PRICE_COLLECTION_FLAG):
        reasons.append("price_collection_done.flag missing_or_stale")

    combined_card = (payload.get("images") or {}).get("combined_card")
    if not combined_card:
        reasons.append("combined_card missing")
    elif not file_is_today(combined_card):
        reasons.append(f"combined_card stale: {combined_card}")

    return reasons


def repair_daily_report_if_needed():
    reasons = needs_report_repair()
    if not reasons:
        return []

    if "price_cache missing_or_stale" in reasons:
        log_repair("auto_repair_blocked: price_cache missing_or_stale")
        raise RuntimeError("fresh price_cache is missing; skip daily report push")

    log_repair("auto_repair_start: " + "; ".join(reasons))
    for cmd in REPAIR_COMMANDS:
        label = " ".join(cmd)
        log_repair(f"run: {label}")
        completed = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
        )
        if completed.returncode != 0:
            log_repair(f"failed: {label}\nstdout={completed.stdout}\nstderr={completed.stderr}")
            raise RuntimeError(f"daily report auto repair failed: {label}")
        if completed.stdout:
            log_repair(f"stdout: {label}\n{completed.stdout[-2000:]}")
        if completed.stderr:
            log_repair(f"stderr: {label}\n{completed.stderr[-2000:]}")
    log_repair("auto_repair_done")
    return reasons


def post_json(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body) if body else {}
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"wecom error: {data}")
    return data


def webhook_key(webhook_url):
    parsed = urllib.parse.urlparse(webhook_url)
    query = urllib.parse.parse_qs(parsed.query)
    key = query.get("key", [None])[0]
    if not key:
        raise RuntimeError("WECOM_WEBHOOK_URL missing key query parameter")
    return key


def upload_file(webhook_url, file_path):
    key = webhook_key(webhook_url)
    upload_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=file"
    boundary = f"----codex{uuid.uuid4().hex}"
    file_path = Path(file_path)
    content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    file_bytes = file_path.read_bytes()
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="media"; filename="{file_path.name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = header + file_bytes + footer

    req = urllib.request.Request(
        upload_url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("errcode", 0) != 0:
        raise RuntimeError(f"upload failed: {data}")
    return data["media_id"]


def send_news(webhook_url, payload, base_url):
    images = payload.get("images", {})
    if images.get("combined_card"):
        cards = [("今日行情日报", images.get("combined_card"))]
    else:
        cards = [
            ("市场追踪日报", images.get("market_daily_card")),
            ("价格监控日报", images.get("price_monitor_card")),
        ]
    articles = []
    for title, path in cards:
        if not path:
            continue
        name = Path(path).name
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", urllib.parse.quote(name))
        articles.append({
            "title": f"{payload.get('date')} {title}",
            "description": payload.get("summary", {}).get("one_sentence", ""),
            "url": url,
            "picurl": url,
        })
    return post_json(webhook_url, {"msgtype": "news", "news": {"articles": articles}})


def signal_url(item):
    return item.get("url") or item.get("source_url") or item.get("link") or (item.get("raw") or {}).get("url") or ""


def signal_summary(item):
    return item.get("summary") or item.get("description") or (item.get("raw") or {}).get("summary") or item.get("title") or ""


def _short_title(item, max_len=16):
    """Get a short display title for link section."""
    title = item.get("title") or "信号"
    # Clean up generic titles (大小写兼容)
    prefixes = [
        "douyin signal: ", "Douyin signal: ",
        "bilibili signal: ", "Bilibili signal: ",
        "xiaohongshu signal: ", "Xiaohongshu signal: ",
        "weibo signal: ", "Weibo signal: ",
    ]
    for prefix in prefixes:
        if title.lower().startswith(prefix.lower()):
            title = title[len(prefix):].strip()
            break
    return title[:max_len]


def _clean_url(url):
    """Strip tracking params from URLs to keep markdown within 4096 bytes."""
    if not url:
        return url
    # douyin: keep only /share/note/ID part
    if "iesdouyin.com/share/note/" in url:
        import re
        m = re.search(r"(https://www\.iesdouyin\.com/share/note/\d+)", url)
        if m:
            return m.group(1)
    # bilibili: already clean
    # xiaohongshu: already clean
    # Generic: strip query params if URL is very long
    if len(url) > 200 and "?" in url:
        return url.split("?")[0]
    return url


def _format_action_item(action):
    """格式化单个动作建议为可读文本"""
    product = action.get("product_name") or action.get("product_id", "未知")
    direction = action.get("direction", "监控")
    change_pct = action.get("change_pct")
    confidence = action.get("confidence_level", "单源")
    auto_confirm = action.get("auto_confirm", True)
    
    # 构建动作前缀
    if direction == "上调":
        prefix = "⬆️ 上调"
    elif direction == "下调":
        prefix = "⬇️ 下调"
    else:
        prefix = "👁️ 监控"
    
    # 构建变动百分比
    pct_str = ""
    if change_pct is not None:
        pct_str = f"{change_pct:+.1f}%"
    
    # 构建确认状态
    confirm_str = "" if auto_confirm else "【需人工确认】"
    
    # 召回画像匹配
    recall_match = action.get("recall_profile_match")
    recall_str = ""
    if recall_match:
        profile_names = {
            "android_high_value": "安卓手机→电脑办公",
            "iphone_high_value": "苹果手机→电脑办公",
            "non_apple_laptop": "非苹果笔记本→电脑办公",
        }
        recall_str = f"|📱{profile_names.get(recall_match, recall_match)}召回"
    
    # 组合完整描述
    parts = [prefix]
    if pct_str:
        parts.append(pct_str)
    parts.append(f"{product}")
    if confirm_str:
        parts.append(confirm_str)
    if recall_str:
        parts.append(recall_str)
    
    return " ".join(parts)


def build_text_summary(payload, base_url=""):
    lines = [
        f"📊 今日行情日报（{payload.get('date')}）",
        payload.get("summary", {}).get("one_sentence", ""),
        "",
    ]

    images = payload.get("images", {})
    if base_url:
        card_links = (("日报合并卡片", images.get("combined_card")),) if images.get("combined_card") else (
            ("市场信号卡片", images.get("market_daily_card")),
            ("价格监控卡片", images.get("price_monitor_card")),
        )
        for label, path in card_links:
            if path:
                name = Path(path).name
                url = urllib.parse.urljoin(base_url.rstrip("/") + "/", urllib.parse.quote(name))
                lines.append(f"{label}：{url}")
        lines.append("")

    # ===== 建议动作部分 =====
    action_items = payload.get("action_items", [])
    if action_items:
        lines.append("🚨 建议动作：")
        # 按置信度和方向排序
        sorted_actions = sorted(action_items, key=lambda x: (
            -x.get("confidence_score", 0),
            x.get("direction", "")
        ))
        for i, action in enumerate(sorted_actions[:8], 1):
            action_text = _format_action_item(action)
            lines.append(f"{i}. {action_text}")
        
        # 统计汇总
        up_count = sum(1 for a in action_items if a.get("direction") == "上调")
        down_count = sum(1 for a in action_items if a.get("direction") == "下调")
        monitor_count = sum(1 for a in action_items if a.get("direction") == "监控")
        need_confirm = sum(1 for a in action_items if not a.get("auto_confirm", True))
        
        summary_parts = []
        if up_count:
            summary_parts.append(f"建议上调{up_count}条")
        if down_count:
            summary_parts.append(f"建议下调{down_count}条")
        if monitor_count:
            summary_parts.append(f"建议监控{monitor_count}条")
        if need_confirm:
            summary_parts.append(f"需人工确认{need_confirm}条")
        
        if summary_parts:
            lines.append(f"📈 汇总：{' | '.join(summary_parts)}")
        lines.append("")

    signals = payload.get("signals", {})
    # Collect clickable links across all levels
    link_items = []
    for level in ("S", "A", "B"):
        for item in (signals.get(level) or [])[:5]:
            url = signal_url(item)
            if url and url.startswith("http"):
                link_items.append((_short_title(item), url))

    # Signal listing (compact, no full URLs)
    added = 0
    for level in ("S", "A", "B"):
        items = signals.get(level) or []
        if not items:
            continue
        lines.append(f"{level}级信号：")
        for item in items[:5]:
            title = item.get("title") or "未命名信号"
            source = item.get("source") or "未知来源"
            published = item.get("published_at") or item.get("publish_date") or ""
            url = signal_url(item)
            # Mark signals with clickable links
            link_mark = "🔗" if (url and url.startswith("http")) else ""
            lines.append(f"- {link_mark}{title}")
            lines.append(f"  来源：{source}" + (f"｜{published}" if published else ""))
            added += 1
        lines.append("")

    if not added:
        lines.append("今日暂无行情信号。")

    # Compact clickable links section
    if link_items:
        lines.append("📋 原文链接：")
        for title, url in link_items:
            clean_url = _clean_url(url)
            lines.append(f"[{title}]({clean_url})")

    # Enforce 4096 byte limit for WeCom markdown
    text = "\n".join(line for line in lines if line is not None)
    encoded = text.encode("utf-8")
    if len(encoded) > 4096:
        # Truncate from the end of links section
        text = encoded[:4080].decode("utf-8", errors="ignore")
        text += "\n...(更多链接见卡片)"
    return text


def send_markdown_summary(webhook_url, payload, base_url=""):
    text = build_text_summary(payload, base_url)
    return post_json(webhook_url, {"msgtype": "markdown", "markdown": {"content": text[:4000]}})


def send_files(webhook_url, payload):
    images = payload.get("images", {})
    keys = ("combined_card",) if images.get("combined_card") else ("market_daily_card", "price_monitor_card")
    for key in keys:
        media_id = upload_file(webhook_url, images[key])
        post_json(webhook_url, {"msgtype": "file", "file": {"media_id": media_id}})


def mark_status(status_value, error=None):
    status = load_json(PUSH_STATUS_FILE)
    now = datetime.now()
    now_text = now.isoformat()
    status["date"] = today_str()
    status["updated_at"] = now_text
    daily = status.setdefault("daily_report", {})
    daily["attempts"] = int(daily.get("attempts", 0)) + 1
    daily["status"] = status_value
    daily["last_error"] = error
    daily["push_time"] = now.strftime("%Y%m%d%H%M%S")
    daily["last_attempt_at"] = now_text
    if status_value == "sent":
        daily["sent"] = True
        daily["sent_at"] = now_text
    save_json(PUSH_STATUS_FILE, status)
    log_event("daily_report.status_marked", status=status_value, error=error, push_time=daily.get("push_time"))


def write_outbox(payload):
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTBOX_DIR / f"daily_report_{payload.get('date')}.json"
    save_json(path, {
        "created_at": datetime.now().isoformat(),
        "reason": "dry_run_or_missing_webhook",
        "text_summary": build_text_summary(payload),
        "payload": payload,
    })
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--webhook-url", default=os.environ.get("WECOM_WEBHOOK_URL", ""))
    parser.add_argument("--base-url", default=os.environ.get("REPORT_CARD_BASE_URL", ""))
    args = parser.parse_args()
    log_event("daily_report_send.start", dry_run=args.dry_run, has_webhook=bool(args.webhook_url), has_base_url=bool(args.base_url))

    if not is_weekday():
        result = {
            "ok": False,
            "phase": "before_repair",
            "errors": ["daily report is disabled on weekends"],
            "warnings": [],
        }
        log_event("daily_report_send.weekend_blocked", ok=False, errors=result["errors"])
        raise SystemExit(json.dumps(result, ensure_ascii=False, indent=2))

    repaired_reasons = repair_daily_report_if_needed()
    guard = check_before_push()
    if not guard["ok"]:
        log_event("daily_report_send.guard_failed", ok=False, errors=guard.get("errors", []), warnings=guard.get("warnings", []))
        if any("push deadline passed" in err for err in guard.get("errors", [])):
            mark_status("missed", "; ".join(guard.get("errors", [])))
        raise SystemExit(json.dumps(guard, ensure_ascii=False, indent=2))

    payload = load_json(PAYLOAD_FILE)

    if args.dry_run or not args.webhook_url:
        outbox = write_outbox(payload)
        log_event("daily_report_send.done", ok=True, mode="dry_run", outbox=str(outbox), auto_repaired=bool(repaired_reasons))
        print(json.dumps({
            "ok": True,
            "mode": "dry_run",
            "outbox": str(outbox),
            "auto_repaired": bool(repaired_reasons),
            "repair_reasons": repaired_reasons,
            "images": payload.get("images", {}),
            "preferred_image": "combined_card" if payload.get("images", {}).get("combined_card") else "split_cards",
            "text_summary": build_text_summary(payload),
        }, ensure_ascii=False, indent=2))
        return

    try:
        mark_status("sending")
        send_markdown_summary(args.webhook_url, payload, args.base_url)
        if args.base_url:
            send_news(args.webhook_url, payload, args.base_url)
            mode = "news"
        else:
            send_files(args.webhook_url, payload)
            mode = "file_upload"
        mark_status("sent")
        log_event("daily_report_send.done", ok=True, mode=mode, auto_repaired=bool(repaired_reasons))
        print(json.dumps({"ok": True, "mode": mode}, ensure_ascii=False, indent=2))
    except Exception as exc:
        mark_status("retrying", str(exc))
        log_exception("daily_report_send.exception", exc)
        raise


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        log_exception("daily_report_send.unhandled_exception", exc)
        raise
