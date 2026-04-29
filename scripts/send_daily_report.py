#!/usr/bin/env python3
"""Send generated daily report cards.

Preferred mode:
- Set WECOM_WEBHOOK_URL
- Set REPORT_CARD_BASE_URL pointing to a public/static directory that exposes
  files in data/report_cards/

Fallback mode:
- If REPORT_CARD_BASE_URL is not set, upload SVG cards as WeCom bot files.
"""
import argparse
import json
import mimetypes
import os
import uuid
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from report_guard import check_before_push


BASE_DIR = Path(__file__).resolve().parent.parent
PAYLOAD_FILE = BASE_DIR / "data" / "daily_report_payload.json"
PUSH_STATUS_FILE = BASE_DIR / "data" / "push_status.json"
OUTBOX_DIR = BASE_DIR / "data" / "outbox"


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
    cards = [
        ("市场追踪日报", images.get("market_daily_card")),
        ("价格监控日报", images.get("price_monitor_card")),
    ]
    articles = []
    for title, path in cards:
        name = Path(path).name
        url = urllib.parse.urljoin(base_url.rstrip("/") + "/", urllib.parse.quote(name))
        articles.append({
            "title": f"{payload.get('date')} {title}",
            "description": payload.get("summary", {}).get("one_sentence", ""),
            "url": url,
            "picurl": url,
        })
    return post_json(webhook_url, {"msgtype": "news", "news": {"articles": articles}})


def send_files(webhook_url, payload):
    images = payload.get("images", {})
    for key in ("market_daily_card", "price_monitor_card"):
        media_id = upload_file(webhook_url, images[key])
        post_json(webhook_url, {"msgtype": "file", "file": {"media_id": media_id}})


def mark_status(status_value, error=None):
    status = load_json(PUSH_STATUS_FILE)
    status["updated_at"] = datetime.now().isoformat()
    daily = status.setdefault("daily_report", {})
    daily["attempts"] = int(daily.get("attempts", 0)) + 1
    daily["status"] = status_value
    daily["last_error"] = error
    if status_value == "sent":
        daily["sent"] = True
        daily["sent_at"] = datetime.now().isoformat()
    save_json(PUSH_STATUS_FILE, status)


def write_outbox(payload):
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTBOX_DIR / f"daily_report_{payload.get('date')}.json"
    save_json(path, {
        "created_at": datetime.now().isoformat(),
        "reason": "dry_run_or_missing_webhook",
        "payload": payload,
    })
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--webhook-url", default=os.environ.get("WECOM_WEBHOOK_URL", ""))
    parser.add_argument("--base-url", default=os.environ.get("REPORT_CARD_BASE_URL", ""))
    args = parser.parse_args()

    guard = check_before_push()
    if not guard["ok"]:
        if any("push deadline passed" in err for err in guard.get("errors", [])):
            mark_status("missed", "; ".join(guard.get("errors", [])))
        raise SystemExit(json.dumps(guard, ensure_ascii=False, indent=2))

    payload = load_json(PAYLOAD_FILE)

    if args.dry_run or not args.webhook_url:
        outbox = write_outbox(payload)
        print(json.dumps({
            "ok": True,
            "mode": "dry_run",
            "outbox": str(outbox),
            "images": payload.get("images", {}),
        }, ensure_ascii=False, indent=2))
        return

    try:
        mark_status("sending")
        if args.base_url:
            send_news(args.webhook_url, payload, args.base_url)
            mode = "news"
        else:
            send_files(args.webhook_url, payload)
            mode = "file_upload"
        mark_status("sent")
        print(json.dumps({"ok": True, "mode": mode}, ensure_ascii=False, indent=2))
    except Exception as exc:
        mark_status("retrying", str(exc))
        raise


if __name__ == "__main__":
    main()
