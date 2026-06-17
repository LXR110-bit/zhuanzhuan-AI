#!/usr/bin/env python3
"""Send filtered market signals to Feishu or write dry-run outbox."""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from feishu_utils import load_dotenv, send_post, write_daily_doc
from runtime_logger import log_event, log_exception


BASE_DIR = Path(__file__).resolve().parent.parent
FILTERED_FILE = BASE_DIR / "data" / "news_signals_filtered.json"
POLICY_CANDIDATES_FILE = BASE_DIR / "data" / "platform_policy_candidates.json"
OUTBOX_DIR = BASE_DIR / "data" / "outbox"

LEVEL_ORDER = {"S": 3, "A": 2, "B": 1}


def load_json(path):
    if not Path(path).exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def load_today_policy_candidates(path=POLICY_CANDIDATES_FILE):
    data = load_json(path)
    if not data:
        return []
    today = today_str()
    if data.get("date") != today and not str(data.get("generated_at") or "").startswith(today):
        return []
    return [item for item in (data.get("items") or []) if isinstance(item, dict)]


def signal_url(item):
    return item.get("url") or item.get("source_url") or item.get("link") or ""


def signal_level(item):
    return str(item.get("level") or item.get("base_level") or "B").replace("级", "").upper()


def selected_items(data, min_level="A"):
    threshold = LEVEL_ORDER[min_level]
    items = data.get("items") if isinstance(data, dict) else data
    result = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        level = signal_level(item)
        if LEVEL_ORDER.get(level, 0) >= threshold:
            result.append(item)
    return result


def build_lines(items, all_count, policy_candidates=None):
    policy_candidates = policy_candidates or []
    if not items and not policy_candidates:
        return [f"今日暂无 S/A 级信号。过滤后信号总数：{all_count}"]
    lines = [f"本次 S/A 级信号 {len(items)} 条，过滤后信号总数：{all_count}"]
    if policy_candidates:
        lines.append(f"平台政策候选线索 {len(policy_candidates)} 条（均需官方/API/截图/OCR复核后才能写入结论）")
    lines.append("")
    for idx, item in enumerate(items[:10], 1):
        level = signal_level(item)
        title = item.get("title") or item.get("summary") or "未命名信号"
        source = item.get("source") or "未知来源"
        published = item.get("published_at") or item.get("publish_date") or ""
        summary = item.get("summary") or item.get("description") or ""
        url = signal_url(item)
        lines.append(f"{idx}. 【{level}】{title}")
        lines.append(f"   来源：{source}" + (f"｜{published}" if published else ""))
        if summary and summary != title:
            lines.append(f"   摘要：{summary[:160]}")
        if url:
            lines.append(f"   链接：{url}")

    if policy_candidates:
        lines.append("")
        lines.append("【平台政策候选｜运营承接预备】")
        for idx, item in enumerate(policy_candidates[:5], 1):
            title = item.get("title") or item.get("summary") or "未命名平台政策线索"
            score = item.get("score")
            evidence_status = item.get("evidence_status") or "pending_verification"
            ops = item.get("ops_playbook") or {}
            url = signal_url(item)
            lines.append(f"{idx}. 【待验证】{title}" + (f"｜分数：{score}" if score is not None else ""))
            lines.append(f"   证据状态：{evidence_status}｜来源：{item.get('source') or 'multi_search'}")
            if ops.get("landing_page"):
                lines.append(f"   承接建议：{ops.get('landing_page')}")
            if ops.get("copy"):
                lines.append(f"   文案方向：{ops.get('copy')[0]}")
            if url:
                lines.append(f"   链接：{url}")
    return lines


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(FILTERED_FILE))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-level", choices=("S", "A", "B"), default="A")
    parser.add_argument("--feishu-webhook-url", default="")
    args = parser.parse_args()

    load_dotenv(BASE_DIR / ".env")
    webhook = args.feishu_webhook_url or os.environ.get("FEISHU_SIGNAL_WEBHOOK_URL") or os.environ.get("FEISHU_WEBHOOK_URL", "")
    data = load_json(Path(args.input))
    items = data.get("items") if isinstance(data, dict) else data or []
    selected = selected_items(data, args.min_level)
    policy_candidates = load_today_policy_candidates()
    lines = build_lines(selected, len(items or []), policy_candidates)
    title = f"【信号监控】{today_str()} 行情信号雷达"
    doc_path = write_daily_doc("signal", title, "\n".join(lines))

    result = {
        "ok": True,
        "date": today_str(),
        "mode": "dry_run" if args.dry_run or not webhook else "feishu",
        "input": str(args.input),
        "selected": len(selected),
        "policy_candidates": len(policy_candidates),
        "doc_path": str(doc_path),
    }

    if args.dry_run or not webhook:
        OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        outbox = OUTBOX_DIR / f"signal_digest_{today_str()}.json"
        save_json(outbox, {"created_at": datetime.now().isoformat(), "title": title, "lines": lines, "selected": selected, "policy_candidates": policy_candidates})
        result["outbox"] = str(outbox)
        log_event("signal_digest.done", **result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    try:
        response = send_post(webhook, title, lines)
        result["response_code"] = response.get("code", response.get("StatusCode", 0))
        log_event("signal_digest.done", **result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        log_exception("signal_digest.exception", exc)
        raise


if __name__ == "__main__":
    main()
