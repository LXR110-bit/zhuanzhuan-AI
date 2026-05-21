#!/usr/bin/env python3
"""Structured runtime logging for the market tracker pipeline."""

import json
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path


CST = timezone(timedelta(hours=8))
BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_LOG_FILE = BASE_DIR / "data" / "logs" / "market_runtime.jsonl"


def now_iso():
    return datetime.now(CST).isoformat()


def runtime_log_file():
    override = os.environ.get("MARKET_TRACKER_LOG_FILE")
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_LOG_FILE


def safe_argv():
    if os.environ.get("MARKET_TRACKER_LOG_RAW_ARGS") == "1":
        return sys.argv
    if len(sys.argv) <= 2:
        return sys.argv
    return sys.argv[:2] + [f"<{len(sys.argv) - 2} args redacted>"]


def json_safe(value):
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except TypeError:
        return str(value)


def log_event(event, **fields):
    path = runtime_log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": now_iso(),
        "event": event,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "argv": safe_argv(),
        "arg_count": max(len(sys.argv) - 2, 0),
    }
    for key, value in fields.items():
        record[key] = json_safe(value)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def log_exception(event, exc):
    log_event(
        event,
        ok=False,
        error=str(exc),
        error_type=exc.__class__.__name__,
        traceback=traceback.format_exc(limit=8),
    )
