#!/usr/bin/env python3
"""Collect a sanitized runtime snapshot for remote debugging."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SNAPSHOT_ROOT = ROOT / "debug_snapshots"

SENSITIVE_KEYS = re.compile(
    r"(token|secret|password|passwd|webhook|key|authorization|cookie)",
    re.IGNORECASE,
)
SENSITIVE_TEXT = re.compile(
    r"((?:key|token|secret|password|webhook)[\"'=:\s]+)[^\"'\s,}]+",
    re.IGNORECASE,
)

RUNTIME_FILES = [
    "data/price_cache.json",
    "data/daily_report_payload.json",
    "data/validation_report.json",
    "data/anomaly_votes.json",
    "data/push_status.json",
    "data/progress.json",
    "data/daytime_scan_status.json",
    "data/cloud_pc_scan_status.json",
    "data/news_signals.json",
    "data/news_signals_filtered.json",
    "data/latest.json",
    "cloud_pc_daily.json",
]


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEYS.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SENSITIVE_TEXT.sub(r"\1[REDACTED]", value)
    return value


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_json(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        write_json(dst, redact(data))
    except Exception as exc:  # Keep broken files inspectable without leaking obvious secrets.
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text(encoding="utf-8", errors="replace")
        dst.write_text(SENSITIVE_TEXT.sub(r"\1[REDACTED]", text), encoding="utf-8")
        write_json(dst.with_suffix(dst.suffix + ".error.json"), {"error": str(exc)})
    return True


def copy_latest_json_files(src_dir: Path, dst_dir: Path, limit: int) -> list[str]:
    copied = []
    if not src_dir.exists():
        return copied
    files = sorted(src_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for src in files[:limit]:
        rel = src.relative_to(ROOT)
        if copy_json(src, dst_dir / src.name):
            copied.append(str(rel))
    return copied


def copy_recent_trend_history(dst_root: Path, days: int) -> list[str]:
    copied = []
    trend_dir = DATA_DIR / "trend_history"
    if not trend_dir.exists():
        return copied
    cutoff_names = set()
    today = datetime.now().date()
    for offset in range(days):
        cutoff_names.add((today.replace()).toordinal() - offset)

    for src in sorted(trend_dir.glob("*/*.json")):
        try:
            file_date = datetime.strptime(src.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date.toordinal() not in cutoff_names:
            continue
        rel = src.relative_to(trend_dir)
        if copy_json(src, dst_root / rel):
            copied.append(str(src.relative_to(ROOT)))
    return copied


def tail_file(src: Path, dst: Path, lines: int) -> bool:
    if not src.exists():
        return False
    content = src.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(SENSITIVE_TEXT.sub(r"\1[REDACTED]", "\n".join(content) + "\n"), encoding="utf-8")
    return True


def collect_logs(dst_root: Path, lines: int) -> list[str]:
    copied = []
    for pattern in (
        "logs/*.log",
        "data/logs/*.log",
        "data/logs/*.jsonl",
        "cloud-pc-monitor/logs/*.log",
        "cloud-pc-monitor/logs/*.md",
    ):
        for src in sorted(ROOT.glob(pattern)):
            rel = src.relative_to(ROOT)
            if tail_file(src, dst_root / rel, lines):
                copied.append(str(rel))
    return copied


def build_manifest(snapshot_dir: Path, copied: dict[str, list[str]]) -> None:
    status = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "snapshot_dir": str(snapshot_dir.relative_to(ROOT)),
        "copied": copied,
        "notes": [
            "This bundle is sanitized and safe to commit for debugging.",
            "Runtime data remains ignored outside debug_snapshots/.",
            "Do not commit raw data/, logs/, or 每日备份/ directories directly.",
        ],
    }
    write_json(snapshot_dir / "manifest.json", status)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--trend-days", type=int, default=30)
    parser.add_argument("--latest-records", type=int, default=7)
    parser.add_argument("--log-lines", type=int, default=400)
    args = parser.parse_args()

    snapshot_dir = SNAPSHOT_ROOT / args.name
    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)
    snapshot_dir.mkdir(parents=True)

    copied = {"runtime_files": [], "daily_price_records": [], "periodic_reports": [], "trend_history": [], "logs": []}

    for rel in RUNTIME_FILES:
        src = ROOT / rel
        if copy_json(src, snapshot_dir / rel):
            copied["runtime_files"].append(rel)

    copied["daily_price_records"] = copy_latest_json_files(
        DATA_DIR / "daily_price_records",
        snapshot_dir / "data" / "daily_price_records",
        args.latest_records,
    )
    copied["periodic_reports"] = copy_latest_json_files(
        DATA_DIR / "periodic_reports",
        snapshot_dir / "data" / "periodic_reports",
        args.latest_records,
    )
    copied["trend_history"] = copy_recent_trend_history(
        snapshot_dir / "data" / "trend_history",
        args.trend_days,
    )
    copied["logs"] = collect_logs(snapshot_dir, args.log_lines)
    build_manifest(snapshot_dir, copied)

    print(json.dumps({"ok": True, "snapshot": str(snapshot_dir), "copied": copied}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
