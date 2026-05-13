#!/usr/bin/env python3
"""
反假装努力 - goal_card 管理脚本
用于读写当天的goal_card JSON文件
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

CST = timezone(timedelta(hours=8))
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def resolve_base_dir():
    goal_card_dir = os.environ.get("GOAL_CARD_DIR")
    if goal_card_dir:
        return Path(goal_card_dir).expanduser().resolve()
    work_dir = os.environ.get("WORK_DIR")
    if work_dir:
        return Path(work_dir).expanduser().resolve() / "反假装努力"
    return SKILL_DIR / "data" / "goal_cards"


BASE_DIR = resolve_base_dir()

def get_today_file():
    today = datetime.now(CST).strftime("%Y-%m-%d")
    return BASE_DIR / f"{today}.json"

def load_data(filepath=None):
    if filepath is None:
        filepath = get_today_file()
    filepath = Path(filepath)
    if filepath.exists():
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"goal_cards": [], "reviews": []}

def save_data(data, filepath=None):
    if filepath is None:
        filepath = get_today_file()
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = filepath.with_suffix(".tmp")
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(filepath)

def get_active_goal(data):
    for card in data.get("goal_cards", []):
        if card.get("status") == "active":
            return card
    return None

def create_goal_card(boss_want, structure, deliverable, deadline, trap_forecast):
    data = load_data()
    card_index = len(data["goal_cards"]) + 1
    today = datetime.now(CST).strftime("%Y-%m-%d")
    card = {
        "card_date": today,
        "card_index": card_index,
        "boss_want": boss_want,
        "structure": structure,
        "deliverable": deliverable,
        "deadline": deadline,
        "trap_forecast": trap_forecast,
        "status": "active"
    }
    data["goal_cards"].append(card)
    save_data(data)
    print(json.dumps({"ok": True, "card": card}, ensure_ascii=False))

def add_review(card_index, did_what, output, verdict, reason, next_action):
    data = load_data()
    today = datetime.now(CST).strftime("%Y-%m-%d")
    review_count = sum(1 for r in data["reviews"] if r.get("card_index") == card_index)
    review = {
        "card_date": today,
        "card_index": card_index,
        "review_index": review_count + 1,
        "did_what": did_what,
        "output": output,
        "verdict": verdict,
        "reason": reason,
        "next_action": next_action
    }
    data["reviews"].append(review)
    save_data(data)
    print(json.dumps({"ok": True, "review": review}, ensure_ascii=False))

def update_goal_status(card_index, status):
    data = load_data()
    for card in data["goal_cards"]:
        if card.get("card_index") == card_index:
            card["status"] = status
            save_data(data)
            print(json.dumps({"ok": True, "card_index": card_index, "status": status}, ensure_ascii=False))
            return
    print(json.dumps({"ok": False, "error": f"card_index {card_index} not found"}, ensure_ascii=False))

def status():
    data = load_data()
    active = get_active_goal(data)
    result = {
        "date": datetime.now(CST).strftime("%Y-%m-%d"),
        "total_cards": len(data["goal_cards"]),
        "active_card": active,
        "total_reviews": len(data["reviews"]),
        "latest_review": data["reviews"][-1] if data["reviews"] else None
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: goal_card_manager.py <command> [args]")
        print("Commands: status, create, review, update_status")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        status()
    elif cmd == "create":
        # goal_card_manager.py create <boss_want> <deliverable> <deadline> <trap_forecast>
        if len(sys.argv) < 6:
            print("Usage: goal_card_manager.py create <boss_want> <deliverable> <deadline> <trap_forecast>")
            sys.exit(1)
        create_goal_card(sys.argv[2], "", sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "review":
        if len(sys.argv) < 8:
            print("Usage: goal_card_manager.py review <card_index> <did_what> <output> <verdict> <reason> <next_action>")
            sys.exit(1)
        add_review(int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7])
    elif cmd == "update_status":
        if len(sys.argv) < 4:
            print("Usage: goal_card_manager.py update_status <card_index> <status>")
            sys.exit(1)
        update_goal_status(int(sys.argv[2]), sys.argv[3])
    else:
        print(f"Unknown command: {cmd}")
