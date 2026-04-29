#!/usr/bin/env python3
"""Initialize daily report state for the current day.

Safe default: if today's files already exist, do not overwrite them unless
`--force` is passed. This prevents an accidental midday run from erasing a
generated report.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SCHEDULE_FILE = BASE_DIR / "config" / "schedule.json"
PUSH_STATUS_FILE = DATA_DIR / "push_status.json"
PAYLOAD_FILE = DATA_DIR / "daily_report_payload.json"
PROGRESS_FILE = DATA_DIR / "progress.json"


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def now_iso():
    return datetime.now().isoformat()


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


def build_push_status(schedule):
    daily = schedule.get("daily_report", {})
    required_cards = daily.get("required_cards", [
        "market_daily_card",
        "price_monitor_card",
    ])
    return {
        "version": "1.0.0",
        "updated_at": now_iso(),
        "date": today_str(),
        "daily_report": {
            "expected_push_time": daily.get("canonical_push_time", daily.get("push_time", "10:00")),
            "status": "pending",
            "attempts": 0,
            "sent": False,
            "sent_at": None,
            "image_required": daily.get("format") == "image_cards",
            "images": {card: None for card in required_cards},
            "last_error": None,
        },
        "alerts": [],
    }


def build_payload():
    return {
        "version": "1.0.0",
        "date": today_str(),
        "generated_at": None,
        "summary": {
            "one_sentence": None,
            "today_action": None,
            "data_quality": "not_generated",
        },
        "signals": {"S": [], "A": [], "B": []},
        "prices": {"updated_at": None, "rows": []},
        "risks": {"drop_alerts": [], "rise_alerts": [], "missing_data": []},
        "images": {"market_daily_card": None, "price_monitor_card": None},
    }


def build_progress():
    return {
        "version": "1.0.0",
        "date": today_str(),
        "updated_at": now_iso(),
        "任务元信息": {
            "状态": "待执行",
            "最后更新时间": now_iso(),
            "当前阶段": "initialized",
        },
        "机型状态": {},
    }


def maybe_write(path, data, force):
    existing = load_json(path)
    if existing.get("date") == today_str() and not force:
        return "kept"
    save_json(path, data)
    return "written"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="overwrite today's files")
    args = parser.parse_args()

    schedule = load_json(SCHEDULE_FILE)
    result = {
        "date": today_str(),
        "push_status": maybe_write(PUSH_STATUS_FILE, build_push_status(schedule), args.force),
        "payload": maybe_write(PAYLOAD_FILE, build_payload(), args.force),
        "progress": maybe_write(PROGRESS_FILE, build_progress(), args.force),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
