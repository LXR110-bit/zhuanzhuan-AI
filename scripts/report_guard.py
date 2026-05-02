#!/usr/bin/env python3
"""
Daily report guard.

Run this before sending the daily report. It blocks the common failure modes:
- pushing before the canonical time
- sending a duplicate report
- sending a full report without required image cards
- rendering from an empty payload
"""
import argparse
import json
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = BASE_DIR / "config" / "schedule.json"
PUSH_STATUS_FILE = BASE_DIR / "data" / "push_status.json"
PAYLOAD_FILE = BASE_DIR / "data" / "daily_report_payload.json"


def load_json(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_hhmm(value):
    return datetime.strptime(value, "%H:%M").time()


def now_hhmm():
    return datetime.now().time().replace(second=0, microsecond=0)


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def has_value(value):
    return value not in (None, "", [], {})


def check_payload(payload):
    errors = []
    warnings = []

    if not payload:
        return ["daily_report_payload.json missing or empty"], warnings

    if payload.get("date") != today_str():
        errors.append(
            f"payload.date must be {today_str()}, got {payload.get('date')}"
        )

    summary = payload.get("summary", {})
    if not has_value(summary.get("one_sentence")):
        errors.append("payload.summary.one_sentence is empty")
    if not has_value(summary.get("today_action")):
        errors.append("payload.summary.today_action is empty")

    prices = payload.get("prices", {})
    if not has_value(prices.get("updated_at")):
        warnings.append("payload.prices.updated_at is empty")
    if not prices.get("rows"):
        warnings.append("payload.prices.rows is empty")
    valid_price_rows = [
        row for row in (prices.get("rows") or [])
        if any(row.get(key) not in (None, "", "-", "—") for key in ("xianyu_market", "xianyu_recycle", "aihuishou", "zhuanzhuan_recycle"))
    ]
    if prices.get("rows") and not valid_price_rows:
        errors.append("payload.prices.rows has no valid price values")

    validation_errors = payload.get("risks", {}).get("validation_errors") or []
    if validation_errors:
        errors.extend(f"validation error: {item}" for item in validation_errors)

    return errors, warnings


def check_images(payload, required_cards):
    errors = []
    images = (payload or {}).get("images", {})
    if has_value(images.get("combined_card")):
        return errors
    for card in required_cards:
        if not has_value(images.get(card)):
            errors.append(f"required image missing: {card}")
    return errors


def check_before_push():
    errors = []
    warnings = []

    config = load_json(CONFIG_FILE)
    status = load_json(PUSH_STATUS_FILE)
    payload = load_json(PAYLOAD_FILE)

    if not config:
        errors.append("config/schedule.json missing or invalid")
        config = {}
    if not status:
        errors.append("data/push_status.json missing or invalid")
        status = {}

    daily_config = config.get("daily_report", {})
    push_status = status.get("daily_report", {})
    push_time = daily_config.get("canonical_push_time") or daily_config.get("push_time")
    deadline = daily_config.get("late_push_policy", {}).get("deadline")
    required_cards = daily_config.get("required_cards", [])

    if daily_config.get("format") != "image_cards":
        errors.append("daily_report.format must be image_cards")

    if status.get("date") != today_str():
        errors.append(
            f"push_status.date must be {today_str()}, got {status.get('date')}"
        )

    if push_status.get("sent") is True:
        errors.append("daily report already sent")

    if push_time:
        current = now_hhmm()
        if current < parse_hhmm(push_time):
            errors.append(f"too early to push: current time is before {push_time}")
        if deadline and current > parse_hhmm(deadline):
            errors.append(f"push deadline passed: after {deadline}")
    else:
        errors.append("canonical push time is missing")

    payload_errors, payload_warnings = check_payload(payload)
    errors.extend(payload_errors)
    warnings.extend(payload_warnings)

    if push_status.get("image_required", True):
        errors.extend(check_images(payload, required_cards))

    return {
        "ok": not errors,
        "checked_at": datetime.now().isoformat(),
        "phase": "before_push",
        "errors": errors,
        "warnings": warnings,
    }


def check_before_image():
    payload = load_json(PAYLOAD_FILE)
    errors, warnings = check_payload(payload)
    return {
        "ok": not errors,
        "checked_at": datetime.now().isoformat(),
        "phase": "before_image",
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=["before_image", "before_push"],
        help="Validation phase",
    )
    args = parser.parse_args()

    if args.phase == "before_image":
        result = check_before_image()
    else:
        result = check_before_push()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
