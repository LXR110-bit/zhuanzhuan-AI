#!/usr/bin/env python3
"""Run the daytime scheduled price scan.

This is separate from the 10:00 daily report push and from the light
10:00/14:00/18:00 signal patrol. It is meant to be invoked by external
schedulers only at the configured price-scan slots.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = BASE_DIR / "scripts"
DATA_DIR = BASE_DIR / "data"
SCHEDULE_FILE = BASE_DIR / "config" / "schedule.json"
STATUS_FILE = DATA_DIR / "daytime_scan_status.json"


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


def parse_time(value):
    return datetime.strptime(value, "%H:%M").time()


def minutes_from_midnight(value):
    t = parse_time(value) if isinstance(value, str) else value
    return t.hour * 60 + t.minute


def current_minutes():
    now = datetime.now()
    return now.hour * 60 + now.minute


def in_quiet_hours(quiet):
    start = minutes_from_midnight(quiet.get("start", "22:30"))
    end = minutes_from_midnight(quiet.get("end", "07:30"))
    now = current_minutes()
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


def nearest_slot(regular_times, tolerance_minutes, forced_slot=None):
    if forced_slot:
        return forced_slot, 0
    now = current_minutes()
    best_slot = None
    best_delta = None
    for slot in regular_times:
        delta = abs(minutes_from_midnight(slot) - now)
        if best_delta is None or delta < best_delta:
            best_slot = slot
            best_delta = delta
    if best_delta is not None and best_delta <= tolerance_minutes:
        return best_slot, best_delta
    return None, best_delta


def ensure_today_status(status):
    if status.get("date") == today_str():
        return status
    return {
        "version": "1.0.0",
        "date": today_str(),
        "updated_at": now_iso(),
        "runs": {},
        "summary": {
            "completed": 0,
            "failed": 0,
            "skipped": 0,
        },
    }


def mark_run(slot, state, error=None):
    status = ensure_today_status(load_json(STATUS_FILE))
    status["updated_at"] = now_iso()
    run = status.setdefault("runs", {}).setdefault(slot, {})
    run.update({
        "slot": slot,
        "status": state,
        "updated_at": now_iso(),
        "error": error,
    })
    summary = {"completed": 0, "failed": 0, "skipped": 0}
    for item in status.get("runs", {}).values():
        if item.get("status") == "completed":
            summary["completed"] += 1
        elif item.get("status") == "failed":
            summary["failed"] += 1
        elif item.get("status") == "skipped":
            summary["skipped"] += 1
    status["summary"] = summary
    save_json(STATUS_FILE, status)
    return status


def validate(schedule, slot, force=False):
    price_scan = schedule.get("price_scan", {})
    regular_times = price_scan.get("regular_times", [])
    tolerance = int(price_scan.get("tolerance_minutes", 20))
    status = ensure_today_status(load_json(STATUS_FILE))
    completed = sum(
        1 for item in status.get("runs", {}).values()
        if item.get("status") == "completed"
    )
    max_daily_runs = int(price_scan.get("max_daily_runs", len(regular_times)))

    selected_slot, delta = nearest_slot(regular_times, tolerance, slot)
    errors = []

    if price_scan.get("forbid_outside_window", True) and in_quiet_hours(schedule.get("quiet_hours", {})):
        errors.append("now is inside quiet hours")
    if not selected_slot:
        errors.append(f"not within {tolerance} minutes of a configured scan slot")
    elif selected_slot not in regular_times:
        errors.append(f"slot {selected_slot} is not configured")
    elif status.get("runs", {}).get(selected_slot, {}).get("status") == "completed":
        errors.append(f"slot {selected_slot} already completed")
    if completed >= max_daily_runs:
        errors.append(f"daily scan limit reached: {completed}/{max_daily_runs}")

    if force:
        errors = []
        selected_slot = selected_slot or slot or datetime.now().strftime("%H:%M")

    return {
        "ok": not errors,
        "slot": selected_slot,
        "delta_minutes": delta,
        "errors": errors,
        "completed": completed,
        "max_daily_runs": max_daily_runs,
    }


def run_command(args):
    result = subprocess.run(
        args,
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


def run_scan_pipeline(no_crawl=False):
    if not no_crawl:
        run_command([sys.executable, str(SCRIPT_DIR / "price_crawler.py"), "once"])
        run_command([sys.executable, str(SCRIPT_DIR / "price_data_validator.py")])
        run_command([sys.executable, str(SCRIPT_DIR / "price_archiver.py"), "archive"])
    run_command([sys.executable, str(SCRIPT_DIR / "generate_daily_report_payload.py")])
    run_command([sys.executable, str(SCRIPT_DIR / "render_report_cards.py")])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["run", "status"], default="run")
    parser.add_argument("--slot", help="configured HH:MM slot, useful for external schedulers")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-crawl", action="store_true", help="refresh payload/cards without network crawling")
    args = parser.parse_args()

    schedule = load_json(SCHEDULE_FILE)
    status = ensure_today_status(load_json(STATUS_FILE))

    if args.command == "status":
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return

    check = validate(schedule, args.slot, args.force)
    if not check["ok"]:
        if check.get("slot"):
            mark_run(check["slot"], "skipped", "; ".join(check["errors"]))
        print(json.dumps(check, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    slot = check["slot"]
    if args.dry_run:
        print(json.dumps({**check, "dry_run": True}, ensure_ascii=False, indent=2))
        return

    mark_run(slot, "running")
    try:
        run_scan_pipeline(no_crawl=args.no_crawl)
        status = mark_run(slot, "completed")
        print(json.dumps({
            "ok": True,
            "slot": slot,
            "status": status.get("runs", {}).get(slot),
            "summary": status.get("summary"),
        }, ensure_ascii=False, indent=2))
    except Exception as exc:
        mark_run(slot, "failed", str(exc))
        raise


if __name__ == "__main__":
    main()
