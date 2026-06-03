#!/usr/bin/env python3
"""Validate staged files do not mix code changes with runtime logs/data."""

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

RAW_LOG_PREFIXES = (
    "logs/",
    "data/logs/",
)
GENERATED_CARD_PREFIXES = (
    "data/report_cards/",
    "data/outbox/",
    "data/periodic_reports/",
)
RUNTIME_DATA_PREFIXES = (
    "data/",
    "每日备份/",
    "白天异动检测/",
)
CODE_PREFIXES = (
    "scripts/",
    "config/",
    "templates/",
    "docs/",
)
OPS_LOG_PREFIXES = (
    "ops_logs/",
    "handoff/codex/",
)
CODE_FILES = (
    "README_文件清单.md",
    ".gitignore",
)
ANTI_COACH_PREFIXES = (
    "skills/anti-involution-coach/",
    "skills/anti-pretend-effort/",
    "zhuanzhuan-anti-coach/",
)
ALLOWED_RUNTIME_FILES = {
    "data/price_cache.json",
}


def staged_files():
    completed = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return [], completed.stderr.strip() or "git diff --cached failed"
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()], None


def startswith_any(path, prefixes):
    return any(path.startswith(prefix) for prefix in prefixes)


def is_code(path):
    return startswith_any(path, CODE_PREFIXES) or path in CODE_FILES


def is_ops_log(path):
    return startswith_any(path, OPS_LOG_PREFIXES)


def is_ops_log_runtime(path):
    setup_files = {
        "ops_logs/TEMPLATE_run_summary.md",
        "ops_logs/runs/.gitkeep",
        "ops_logs/schedules/.gitkeep",
        "handoff/codex/TEMPLATE_issue.md",
    }
    return is_ops_log(path) and path not in setup_files


def is_runtime(path):
    return startswith_any(path, RUNTIME_DATA_PREFIXES) and path not in ALLOWED_RUNTIME_FILES


def main():
    files, error = staged_files()
    if error:
        print(json.dumps({"ok": False, "error": error}, ensure_ascii=False, indent=2))
        return 2

    violations = []
    raw_logs = [path for path in files if startswith_any(path, RAW_LOG_PREFIXES)]
    generated_cards = [path for path in files if startswith_any(path, GENERATED_CARD_PREFIXES)]
    anti_coach = [path for path in files if startswith_any(path, ANTI_COACH_PREFIXES)]
    code_files = [path for path in files if is_code(path)]
    runtime_files = [path for path in files if is_runtime(path) and not is_ops_log(path)]
    ops_logs = [path for path in files if is_ops_log(path)]
    ops_log_runtime = [path for path in files if is_ops_log_runtime(path)]

    if raw_logs:
        violations.append({
            "rule": "raw_logs_forbidden",
            "message": "不要直接提交原始日志；请用 scripts/collect_debug_snapshot.py 生成脱敏快照。",
            "files": raw_logs,
        })
    if generated_cards:
        violations.append({
            "rule": "generated_cards_forbidden",
            "message": "不要直接提交生成卡片/导出文件；需要排障时提交 debug_snapshots/。",
            "files": generated_cards,
        })
    if anti_coach:
        violations.append({
            "rule": "anti_coach_forbidden_in_market_repo",
            "message": "行情仓不得提交反卷教练 skill 或运行数据。",
            "files": anti_coach,
        })
    
    if code_files and ops_log_runtime:
        violations.append({
            "rule": "ops_log_code_mixed_commit",
            "message": "Coze 运行日志 commit 不得和代码/配置/文档变更混在同一个 commit。",
            "code_files": code_files,
            "ops_log_files": ops_log_runtime,
        })

    if code_files and runtime_files:
        violations.append({
            "rule": "code_runtime_mixed_commit",
            "message": "代码/配置/文档变更不得和运行态 data/ 日志类文件混在同一个 commit。",
            "code_files": code_files,
            "runtime_files": runtime_files,
        })

    result = {
        "ok": not violations,
        "repo": "zhuanzhuan-AI",
        "checked": "staged_files",
        "staged_count": len(files),
        "ops_log_files": ops_logs,
        "violations": violations,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
