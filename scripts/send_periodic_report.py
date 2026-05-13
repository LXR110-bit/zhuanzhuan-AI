#!/usr/bin/env python3
"""Send weekly/monthly trend report cards via WeCom webhook."""
import argparse
import base64
import hashlib
import json
import os
import uuid
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "periodic_reports"
PUSH_STATUS_FILE = DATA_DIR / "push_status.json"


def load_json(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


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
    file_bytes = file_path.read_bytes()
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="media"; filename="{file_path.name}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
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


def post_image(webhook_url, file_path):
    file_path = Path(file_path)
    file_bytes = file_path.read_bytes()
    payload = {
        "msgtype": "image",
        "image": {
            "base64": base64.b64encode(file_bytes).decode("ascii"),
            "md5": hashlib.md5(file_bytes).hexdigest(),
        },
    }
    return post_json(webhook_url, payload)


def build_text_summary(payload):
    summary = payload.get("summary", {})
    period_label = payload.get("period_label", "")
    date = payload.get("date", "")
    headline = summary.get("headline", "")
    lines = [
        f"📊 {period_label}价格趋势报告（{date}）",
        summary.get("message", ""),
    ]
    if headline:
        lines.append(f"趋势: {headline}")

    cat_trends = payload.get("category_trends", [])
    if cat_trends:
        lines.append("")
        lines.append("品类趋势:")
        for ct in cat_trends[:6]:
            pct = ct.get("avg_change_pct")
            pct_str = f"{pct:+.1f}%" if pct is not None else "—"
            lines.append(f"  {ct['category']}: {pct_str} ({ct.get('trend', '')})")

    anomaly = payload.get("anomaly_summary", {})
    if anomaly.get("total_anomalies"):
        lines.append(f"\n异动: 共{anomaly['total_anomalies']}次")

    drift = payload.get("baseline_drift", {})
    if drift.get("products_drifted"):
        lines.append(f"基准线漂移: {drift['products_drifted']}个产品")

    return "\n".join(lines)


def mark_periodic_status(period, status_value, error=None):
    status = load_json(PUSH_STATUS_FILE)
    status["updated_at"] = datetime.now().isoformat()
    periodic = status.setdefault("periodic_report", {})
    entry = periodic.setdefault(period, {})
    entry["status"] = status_value
    entry["last_push_at"] = datetime.now().isoformat()
    entry["last_error"] = error
    save_json(PUSH_STATUS_FILE, status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=["weekly", "monthly"], required=True)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--webhook-url", default=os.environ.get("WECOM_WEBHOOK_URL", ""))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    today = datetime.now().strftime("%Y-%m-%d")
    payload_file = output_dir / f"{today}_{args.period}_trend_payload.json"
    image_file = output_dir / f"{today}_{args.period}_trend_card.png"

    if not payload_file.exists():
        raise SystemExit(f"payload not found: {payload_file}")

    payload = load_json(payload_file)

    if not image_file.exists():
        print(f"[warn] image not found: {image_file}, sending text only")

    if args.dry_run or not args.webhook_url:
        print(json.dumps({
            "ok": True, "mode": "dry_run", "period": args.period,
            "text_summary": build_text_summary(payload),
            "image_exists": image_file.exists(),
        }, ensure_ascii=False, indent=2))
        return

    try:
        mark_periodic_status(args.period, "sending")
        text = build_text_summary(payload)
        post_json(args.webhook_url, {
            "msgtype": "markdown",
            "markdown": {"content": text[:4000]},
        })
        if image_file.exists():
            try:
                post_image(args.webhook_url, image_file)
            except Exception:
                media_id = upload_file(args.webhook_url, image_file)
                post_json(args.webhook_url, {"msgtype": "file", "file": {"media_id": media_id}})
        mark_periodic_status(args.period, "sent")
        print(json.dumps({"ok": True, "period": args.period, "mode": "sent"}, ensure_ascii=False, indent=2))
    except Exception as exc:
        mark_periodic_status(args.period, "failed", str(exc))
        raise


if __name__ == "__main__":
    main()
