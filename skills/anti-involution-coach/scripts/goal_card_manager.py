#!/usr/bin/env python3
"""
反卷教练 - goal_card 管理脚本
用于读写当天的 goal_card / review / daily_summary / heartbeat JSON 文件。

调用方约定：
- 每次 agent 被定时器或主人唤起，先 `status`，读到 active_card / latest_review。
- 任何节点动作完成后，写一条 `heartbeat`，包含 active_card_found / push_status。
- Phase1 完成写 `create`；Phase2 完成写 `review`；Phase3 完成写 `summary`。
"""

import json
import os
import sys
import time
import fcntl
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
        return Path(work_dir).expanduser().resolve() / "反卷教练"
    return SKILL_DIR / "data" / "goal_cards"


BASE_DIR = resolve_base_dir()

VALID_STATUSES = {"active", "completed", "abandoned"}
VALID_REVIEW_VERDICTS = {"在轨", "跑偏", "伪装忙碌"}
VALID_SUMMARY_VERDICTS = {"有效推进", "部分推进", "假装努力"}
VALID_EVENT_TYPES = {"goal_start", "heartbeat", "segment_close", "daily_close"}
VALID_PUSH_STATUSES = {"success", "failed", "skipped", "unknown"}
VALID_OUTPUT_CHANNELS = {"coze"}
DEFAULT_DATA = {
    "goal_cards": [],
    "reviews": [],
    "daily_summaries": [],
    "heartbeat_logs": [],
}


def today_str():
    return datetime.now(CST).strftime("%Y-%m-%d")


def now_str():
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def get_today_file():
    return BASE_DIR / f"{today_str()}.json"


def normalize_data(data):
    for key, default_value in DEFAULT_DATA.items():
        data.setdefault(key, list(default_value))
    return data


def print_error(message, exit_code=1):
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(exit_code)


def lock_file_for(filepath):
    return filepath.with_suffix(filepath.suffix + ".lock")


class FileLock:
    def __init__(self, filepath):
        self.lock_path = lock_file_for(Path(filepath))
        self.handle = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.lock_path, "w", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()


def load_data(filepath=None):
    if filepath is None:
        filepath = get_today_file()
    filepath = Path(filepath)
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return normalize_data(json.load(f))
    return normalize_data({})


def save_data(data, filepath=None):
    if filepath is None:
        filepath = get_today_file()
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = filepath.with_name(f"{filepath.name}.{os.getpid()}.{time.time_ns()}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(normalize_data(data), f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, filepath)


def update_data(mutator, filepath=None):
    if filepath is None:
        filepath = get_today_file()
    filepath = Path(filepath)
    with FileLock(filepath):
        data = load_data(filepath)
        result = mutator(data)
        save_data(data, filepath)
    return result


def get_active_goal(data):
    active_cards = [card for card in data.get("goal_cards", []) if card.get("status") == "active"]
    return active_cards[0] if active_cards else None


def find_card(data, card_index):
    for card in data.get("goal_cards", []):
        if card.get("card_index") == card_index:
            return card
    return None


def get_latest_review_for_card(data, card_index):
    matches = [r for r in data.get("reviews", []) if r.get("card_index") == card_index]
    return matches[-1] if matches else None


def create_goal_card(boss_want, deliverable, min_version, deadline, trap_forecast, first_cut):
    def mutator(data):
        active = get_active_goal(data)
        if active:
            print_error(f"active goal_card already exists: card_index {active.get('card_index')}")
        card_index = len(data["goal_cards"]) + 1
        card = {
            "card_date": today_str(),
            "card_index": card_index,
            "boss_want": boss_want,
            "deliverable": deliverable,
            "min_version": min_version,
            "deadline": deadline,
            "trap_forecast": trap_forecast,
            "first_cut": first_cut,
            "status": "active",
        }
        data["goal_cards"].append(card)
        return card

    card = update_data(mutator)
    print(json.dumps({"ok": True, "card": card}, ensure_ascii=False))


def add_review(card_index, did_what, output, verdict, reason, next_action):
    if verdict not in VALID_REVIEW_VERDICTS:
        print_error(f"invalid verdict: {verdict}")

    def mutator(data):
        card = find_card(data, card_index)
        if not card:
            print_error(f"card_index {card_index} not found")
        review_count = sum(1 for r in data["reviews"] if r.get("card_index") == card_index)
        review = {
            "card_date": today_str(),
            "card_index": card_index,
            "review_index": review_count + 1,
            "did_what": did_what,
            "output": output,
            "verdict": verdict,
            "reason": reason,
            "next_action": next_action,
        }
        data["reviews"].append(review)
        return review

    review = update_data(mutator)
    print(json.dumps({"ok": True, "review": review}, ensure_ascii=False))


def add_daily_summary(final_output, goal_delta, pretend_effort, effective_action, verdict, tomorrow_first_cut, coach_note):
    if verdict not in VALID_SUMMARY_VERDICTS:
        print_error(f"invalid summary verdict: {verdict}")

    def mutator(data):
        summary = {
            "summary_date": today_str(),
            "summary_index": len(data["daily_summaries"]) + 1,
            "final_output": final_output,
            "goal_delta": goal_delta,
            "pretend_effort": pretend_effort,
            "effective_action": effective_action,
            "verdict": verdict,
            "tomorrow_first_cut": tomorrow_first_cut,
            "coach_note": coach_note,
        }
        data["daily_summaries"].append(summary)
        return summary

    summary = update_data(mutator)
    print(json.dumps({"ok": True, "daily_summary": summary}, ensure_ascii=False))


def update_goal_status(card_index, status):
    if status not in VALID_STATUSES:
        print_error(f"invalid status: {status}")

    def mutator(data):
        card = find_card(data, card_index)
        if not card:
            print_error(f"card_index {card_index} not found")
        if status == "active":
            active = get_active_goal(data)
            if active and active.get("card_index") != card_index:
                print_error(f"another active goal_card already exists: card_index {active.get('card_index')}")
        card["status"] = status
        return {"card_index": card_index, "status": status}

    result = update_data(mutator)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


def add_heartbeat(node, event_type, active_card_found, action_taken, push_status="success", reason="", output_channel="coze"):
    """
    写入一条心跳诊断日志。Coze 不可靠时，靠这张表反查哑火节点。

    node: 10:00 / 10:30 / 12:00 / 13:30 / 14:00 / ... / 21:00
    event_type: goal_start | heartbeat | segment_close | daily_close
    active_card_found: "true" / "false"
    push_status: success | failed | skipped | unknown
    output_channel: coze
    """
    if event_type not in VALID_EVENT_TYPES:
        print_error(f"invalid event_type: {event_type}")
    if str(active_card_found).lower() not in {"true", "false"}:
        print_error("active_card_found must be true or false")
    if push_status not in VALID_PUSH_STATUSES:
        print_error(f"invalid push_status: {push_status}")
    if output_channel not in VALID_OUTPUT_CHANNELS:
        print_error(f"invalid output_channel for coaching message: {output_channel}")

    def mutator(data):
        file_path = str(get_today_file())
        entry = {
            "heartbeat_time": now_str(),
            "node": node,
            "event_type": event_type,
            "goal_card_path": file_path,
            "active_card_found": str(active_card_found).lower() == "true",
            "action_taken": action_taken,
            "push_status": push_status,
            "reason": reason,
            "output_channel": output_channel,
        }
        data["heartbeat_logs"].append(entry)
        return entry

    entry = update_data(mutator)
    print(json.dumps({"ok": True, "heartbeat": entry}, ensure_ascii=False))


def status():
    """
    冷启动第一步必跑。返回的内容是教练接续上下文的全部输入：
    active_card 是当前主目标，latest_review_for_active 是上一次问到了哪。
    """
    filepath = get_today_file()
    with FileLock(filepath):
        data = load_data(filepath)
    active = get_active_goal(data)
    latest_review_for_active = None
    if active:
        latest_review_for_active = get_latest_review_for_card(data, active.get("card_index"))
    result = {
        "date": today_str(),
        "now": now_str(),
        "total_cards": len(data["goal_cards"]),
        "active_card": active,
        "latest_review_for_active": latest_review_for_active,
        "total_reviews": len(data.get("reviews", [])),
        "latest_review": data["reviews"][-1] if data.get("reviews") else None,
        "total_daily_summaries": len(data.get("daily_summaries", [])),
        "latest_daily_summary": data.get("daily_summaries", [])[-1] if data.get("daily_summaries") else None,
        "total_heartbeats": len(data.get("heartbeat_logs", [])),
        "latest_heartbeat": data.get("heartbeat_logs", [])[-1] if data.get("heartbeat_logs") else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


USAGE = """Usage: goal_card_manager.py <command> [args]

Commands:
  status
      Read today's state. Always run this first on cold start.

  create <boss_want> <deliverable> <min_version> <deadline> <trap_forecast> <first_cut>
      Write a new goal_card from Phase1 five answers.

  review <card_index> <did_what> <output> <verdict> <reason> <next_action>
      Write a Phase2 review entry. verdict in {在轨, 跑偏, 伪装忙碌}.

  summary <final_output> <goal_delta> <pretend_effort> <effective_action> <verdict> <tomorrow_first_cut> <coach_note>
      Write a Phase3 daily summary. verdict in {有效推进, 部分推进, 假装努力}.

  update_status <card_index> <status>
      status in {active, completed, abandoned}.

  heartbeat <node> <event_type> <active_card_found> <action_taken> [push_status] [reason] [output_channel]
      Log a heartbeat run. event_type in {goal_start, heartbeat, segment_close, daily_close}.
      active_card_found is "true" or "false". push_status defaults to success.
      output_channel defaults to coze; coaching messages reject all other channels.
"""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "status":
        status()
    elif cmd == "create":
        if len(sys.argv) < 8:
            print("Usage: goal_card_manager.py create <boss_want> <deliverable> <min_version> <deadline> <trap_forecast> <first_cut>")
            sys.exit(1)
        create_goal_card(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7])
    elif cmd == "review":
        if len(sys.argv) < 8:
            print("Usage: goal_card_manager.py review <card_index> <did_what> <output> <verdict> <reason> <next_action>")
            sys.exit(1)
        add_review(int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7])
    elif cmd == "summary":
        if len(sys.argv) < 9:
            print("Usage: goal_card_manager.py summary <final_output> <goal_delta> <pretend_effort> <effective_action> <verdict> <tomorrow_first_cut> <coach_note>")
            sys.exit(1)
        add_daily_summary(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6], sys.argv[7], sys.argv[8])
    elif cmd == "update_status":
        if len(sys.argv) < 4:
            print("Usage: goal_card_manager.py update_status <card_index> <status>")
            sys.exit(1)
        update_goal_status(int(sys.argv[2]), sys.argv[3])
    elif cmd == "heartbeat":
        if len(sys.argv) < 6:
            print("Usage: goal_card_manager.py heartbeat <node> <event_type> <active_card_found> <action_taken> [push_status] [reason] [output_channel]")
            sys.exit(1)
        push_status = sys.argv[6] if len(sys.argv) > 6 else "success"
        reason = sys.argv[7] if len(sys.argv) > 7 else ""
        output_channel = sys.argv[8] if len(sys.argv) > 8 else "coze"
        add_heartbeat(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], push_status, reason, output_channel)
    else:
        print(f"Unknown command: {cmd}\n")
        print(USAGE)
        sys.exit(1)
