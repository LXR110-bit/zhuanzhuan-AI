#!/usr/bin/env python3
"""Validate anti-involution coach schedule descriptions are Coze-only."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "anti-involution-coach"
POLICY_FILE = SKILL_DIR / "policy" / "channel_policy.json"
DEFAULT_SCAN_TARGETS = [
    SKILL_DIR / "templates" / "coze_schedules",
    SKILL_DIR / "config" / "schedule.md",
    SKILL_DIR / "config" / "schema.md",
]
SKIP_FILES = {
    SKILL_DIR / "SKILL.md",
    POLICY_FILE,
}


def load_policy():
    with open(POLICY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def expand_targets(args):
    targets = [Path(arg).expanduser() for arg in args] if args else DEFAULT_SCAN_TARGETS
    files = []
    for target in targets:
        path = target if target.is_absolute() else ROOT / target
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*") if p.is_file() and p not in SKIP_FILES))
        elif path.is_file():
            if path not in SKIP_FILES:
                files.append(path)
        else:
            print(json.dumps({"ok": False, "error": f"target not found: {target}"}, ensure_ascii=False))
            sys.exit(2)
    return files


def find_violations(files, forbidden_terms):
    violations = []
    lowered_terms = []
    seen_terms = set()
    for term in forbidden_terms:
        lowered = term.lower()
        if lowered in seen_terms:
            continue
        seen_terms.add(lowered)
        lowered_terms.append((term, lowered))
    for file_path in files:
        text = file_path.read_text(encoding="utf-8")
        lowered_text = text.lower()
        for original, lowered in lowered_terms:
            if lowered in lowered_text:
                violations.append({
                    "file": display_path(file_path),
                    "term": original,
                })
    return violations


def display_path(file_path):
    try:
        return str(file_path.relative_to(ROOT))
    except ValueError:
        return str(file_path)


def main():
    policy = load_policy()
    files = expand_targets(sys.argv[1:])
    violations = find_violations(files, policy["forbidden_terms"] + policy["forbidden_output_channels"])
    if violations:
        print(json.dumps({
            "ok": False,
            "error": "anti-involution coach channel pollution detected",
            "violations": violations,
        }, ensure_ascii=False, indent=2))
        sys.exit(1)
    print(json.dumps({
        "ok": True,
        "checked_files": [display_path(path) for path in files],
        "allowed_output_channels": policy["allowed_output_channels"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
