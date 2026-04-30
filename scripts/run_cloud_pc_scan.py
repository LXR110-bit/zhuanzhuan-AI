#!/usr/bin/env python3
"""Run the restored cloud-PC scheduled scan module.

This keeps the original cloud-pc-monitor track separate from the daytime
anomaly scan and from the 10:00 market daily push.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT_DIR = BASE_DIR / "scripts"
MONITOR_DIR = BASE_DIR / "cloud-pc-monitor"
MONITOR_SCRIPT_DIR = MONITOR_DIR / "scripts"
MONITOR_LOG_DIR = MONITOR_DIR / "logs"
DATA_DIR = BASE_DIR / "data"
SCHEDULE_FILE = BASE_DIR / "config" / "schedule.json"
STATUS_FILE = DATA_DIR / "cloud_pc_scan_status.json"


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


def minutes_from_midnight(value):
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def current_minutes():
    now = datetime.now()
    return now.hour * 60 + now.minute


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
        "summary": {"completed": 0, "failed": 0, "skipped": 0},
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
    cloud_scan = schedule.get("cloud_pc_scan", {})
    regular_times = cloud_scan.get("regular_times", [])
    tolerance = int(cloud_scan.get("tolerance_minutes", schedule.get("price_scan", {}).get("tolerance_minutes", 20)))
    status = ensure_today_status(load_json(STATUS_FILE))
    completed = sum(
        1 for item in status.get("runs", {}).values()
        if item.get("status") == "completed"
    )
    max_daily_runs = int(cloud_scan.get("max_daily_runs", len(regular_times)))
    selected_slot, delta = nearest_slot(regular_times, tolerance, slot)
    errors = []

    if not selected_slot:
        errors.append(f"not within {tolerance} minutes of a configured cloud-PC scan slot")
    elif selected_slot not in regular_times:
        errors.append(f"slot {selected_slot} is not configured for cloud-PC scan")
    elif status.get("runs", {}).get(selected_slot, {}).get("status") == "completed":
        errors.append(f"slot {selected_slot} already completed")
    if completed >= max_daily_runs:
        errors.append(f"daily cloud-PC scan limit reached: {completed}/{max_daily_runs}")

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


def run_command(args, cwd):
    result = subprocess.run(args, cwd=str(cwd), text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result.stdout


def run_cloud_pc_pipeline(refresh_report=True):
    log_parts = []
    log_parts.append(run_command([sys.executable, str(MONITOR_SCRIPT_DIR / "analyze.py")], MONITOR_DIR))
    log_parts.append(run_command([sys.executable, str(MONITOR_SCRIPT_DIR / "price_archiver.py"), "archive"], MONITOR_DIR))
    log_parts.append(run_command([sys.executable, str(MONITOR_SCRIPT_DIR / "output_for_daily.py")], BASE_DIR))
    if refresh_report:
        log_parts.append(run_command([sys.executable, str(SCRIPT_DIR / "generate_daily_report_payload.py")], BASE_DIR))
        log_parts.append(run_command([sys.executable, str(SCRIPT_DIR / "render_cards_html.py")], BASE_DIR))
    MONITOR_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = MONITOR_LOG_DIR / f"monitor_{datetime.now().strftime('%Y-%m-%d_%H%M')}.log"
    log_file.write_text("\n".join(log_parts), encoding="utf-8")
    return str(log_file)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", nargs="?", choices=["run", "status"], default="run")
    parser.add_argument("--slot", help="configured HH:MM slot")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-report-refresh", action="store_true")
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
        log_file = run_cloud_pc_pipeline(refresh_report=not args.no_report_refresh)
        status = mark_run(slot, "completed")
        print(json.dumps({
            "ok": True,
            "slot": slot,
            "log": log_file,
            "status": status.get("runs", {}).get(slot),
            "summary": status.get("summary"),
        }, ensure_ascii=False, indent=2))
    except Exception as exc:
        mark_run(slot, "failed", str(exc))
        raise


if __name__ == "__main__":
    main()
