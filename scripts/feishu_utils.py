#!/usr/bin/env python3
"""Feishu webhook helpers for market monitor agents.

This module intentionally supports only incoming webhook bots. It never logs or
prints webhook URLs and can generate daily markdown documents for later Feishu
knowledge-base synchronization.
"""
import json
import os
import urllib.request
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FEISHU_DOC_DIR = DATA_DIR / "feishu_daily_docs"


def load_dotenv(path=None):
    path = Path(path or BASE_DIR / ".env")
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return True


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def post_json(url, payload, timeout=20):
    if not url:
        raise RuntimeError("missing Feishu webhook url")
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body) if body else {}
    code = data.get("code", data.get("StatusCode", 0))
    if code not in (0, "0", None):
        raise RuntimeError(f"feishu error: {data}")
    return data


def text_payload(text):
    return {"msg_type": "text", "content": {"text": text}}


def post_payload(title, lines):
    content = []
    for line in lines:
        if line is None:
            continue
        content.append([{"tag": "text", "text": str(line)}])
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": content,
                }
            }
        },
    }


def send_text(webhook_url, text):
    return post_json(webhook_url, text_payload(text))


def send_post(webhook_url, title, lines):
    return post_json(webhook_url, post_payload(title, lines))


def write_daily_doc(agent_role, title, body, date=None):
    """Write a markdown daily document draft for Feishu KB sync.

    agent_role should be price or signal. The output is runtime data and is not
    intended for code commits.
    """
    date = date or today_str()
    safe_role = "price" if agent_role == "price" else "signal"
    out_dir = FEISHU_DOC_DIR / date
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{safe_role}.md"
    content = f"# {title}\n\n- 日期：{date}\n- 模块：{safe_role}\n- 生成时间：{datetime.now().isoformat()}\n- feishu_sync_status: pending\n\n{body.strip()}\n"
    path.write_text(content, encoding="utf-8")
    return path
