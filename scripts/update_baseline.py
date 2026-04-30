#!/usr/bin/env python3
"""Create or apply weekly baseline update proposals.

Modes:
  proposal (default)   — from price_cache, write proposal for manual confirmation
  adaptive             — from 14-day trend_history, auto-apply <5% changes
  apply-confirmed      — apply manually confirmed proposals
"""
import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
BASELINE_FILE = CONFIG_DIR / "baseline.json"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
PROPOSAL_FILE = DATA_DIR / "baseline_update_proposal.json"
TREND_HISTORY_DIR = DATA_DIR / "trend_history"
BASELINE_HISTORY_DIR = DATA_DIR / "baseline_history"
UPDATE_LOG_FILE = DATA_DIR / "baseline_update_log.json"

ROLLING_WINDOW_DAYS = 14
AUTO_APPLY_THRESHOLD_PCT = 5.0
MIN_SAMPLES = 7


def now_iso():
    return datetime.now().isoformat()


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


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
def baseline_key(product_id):
    return product_id.replace("-", "_").replace(" ", "_")


def market_price(item):
    for path in (
        ("xianyu_market", "avg"),
        ("xianyu_official", "price"),
        ("aihuishou", "tansuo_price"),
    ):
        cur = item
        for key in path:
            cur = cur.get(key) if isinstance(cur, dict) else None
        if isinstance(cur, (int, float)):
            return float(cur)
    return None


def build_proposal(baseline, cache):
    proposals = []
    existing = baseline.get("baselines", {})
    for product_id, item in (cache.get("prices") or {}).items():
        price = market_price(item)
        if price is None:
            continue
        key = baseline_key(product_id)
        old = existing.get(key, {})
        old_avg = old.get("avg") or old.get("second_hand_avg") or old.get("official")
        change_pct = None
        if isinstance(old_avg, (int, float)) and old_avg:
            change_pct = (price - old_avg) / old_avg * 100
        proposals.append({
            "product_id": product_id,
            "baseline_key": key,
            "product_name": item.get("product_name") or product_id,
            "old_avg": old_avg,
            "proposed_avg": round(price, 2),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "source": "data/price_cache.json",
            "requires_manual_confirmation": True,
        })
    return {
        "version": "1.0.0",
        "date": today_str(),
        "generated_at": now_iso(),
        "status": "pending_manual_confirmation",
        "proposals": proposals,
    }


def apply_confirmed(baseline, proposal):
    updated = dict(baseline)
    baselines = dict(updated.get("baselines", {}))
    for item in proposal.get("proposals", []):
        if not item.get("confirmed"):
            continue
        key = item["baseline_key"]
        old = dict(baselines.get(key, {}))
        old["avg"] = item["proposed_avg"]
        old["source"] = "weekly_baseline_update"
        old["updated"] = today_str()
        baselines[key] = old
    updated["baselines"] = baselines
    updated["updated_at"] = now_iso()
    return updated

def load_trend_prices(product_dir, days=ROLLING_WINDOW_DAYS):
    """从 trend_history 加载最近 N 天的价格序列"""
    prices = []
    product_dir = Path(product_dir)
    if not product_dir.exists():
        return prices
    for f in sorted(product_dir.glob("*.json"))[-days:]:
        raw = load_json(f)
        data = raw.get("data") or raw
        for path in (
            ("xianyu_market", "avg"),
            ("aihuishou", "tansuo_price"),
            ("xianyu_official", "price"),
        ):
            cur = data
            for key in path:
                cur = cur.get(key) if isinstance(cur, dict) else None
            if isinstance(cur, (int, float)):
                prices.append(float(cur))
                break
    return prices


def build_adaptive_proposal(baseline, trend_history_dir):
    """基于14天滚动窗口构建自适应更新提案"""
    trend_dir = Path(trend_history_dir)
    if not trend_dir.exists():
        return {"version": "2.0.0", "date": today_str(), "generated_at": now_iso(),
                "status": "no_trend_data", "proposals": []}

    existing = baseline.get("baselines", {})
    proposals = []

    for product_dir in sorted(p for p in trend_dir.iterdir() if p.is_dir()):
        product_id = product_dir.name
        prices = load_trend_prices(product_dir, ROLLING_WINDOW_DAYS)
        key = baseline_key(product_id)
        old = existing.get(key, {})
        old_avg = old.get("avg") or old.get("second_hand_avg") or old.get("official")

        if len(prices) < MIN_SAMPLES:
            proposals.append({
                "product_id": product_id,
                "baseline_key": key,
                "old_avg": old_avg,
                "proposed_avg": None,
                "change_pct": None,
                "status": "skipped_insufficient_data",
                "sample_count": len(prices),
                "auto_apply": False,
                "requires_confirmation": False,
            })
            continue

        proposed_avg = round(statistics.median(prices), 2)
        change_pct = None
        if isinstance(old_avg, (int, float)) and old_avg:
            change_pct = round((proposed_avg - old_avg) / old_avg * 100, 2)

        auto_apply = change_pct is not None and abs(change_pct) < AUTO_APPLY_THRESHOLD_PCT
        requires_confirmation = change_pct is not None and abs(change_pct) >= AUTO_APPLY_THRESHOLD_PCT

        proposals.append({
            "product_id": product_id,
            "baseline_key": key,
            "old_avg": old_avg,
            "proposed_avg": proposed_avg,
            "change_pct": change_pct,
            "sample_count": len(prices),
            "data_window": f"{ROLLING_WINDOW_DAYS}d",
            "auto_apply": auto_apply,
            "requires_confirmation": requires_confirmation,
            "status": "auto_apply" if auto_apply else (
                "requires_confirmation" if requires_confirmation else "new_product"),
        })

    return {
        "version": "2.0.0",
        "date": today_str(),
        "generated_at": now_iso(),
        "trigger": "auto_weekly",
        "proposals": proposals,
    }

def save_baseline_version(baseline, changes, trigger="manual"):
    """保存 baseline 版本快照到 baseline_history/"""
    BASELINE_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    today = today_str()
    existing_versions = sorted(BASELINE_HISTORY_DIR.glob(f"{today}_v*.json"))
    version = len(existing_versions) + 1
    snapshot_file = BASELINE_HISTORY_DIR / f"{today}_v{version}.json"

    auto_count = sum(1 for c in changes if c.get("auto_apply"))
    pending_count = sum(1 for c in changes if c.get("requires_confirmation"))
    skipped_count = sum(1 for c in changes if c.get("status") == "skipped_insufficient_data")

    snapshot = {
        "version": version,
        "date": today,
        "created_at": now_iso(),
        "trigger": trigger,
        "baseline_snapshot": baseline.get("baselines", {}),
        "changes_applied": changes,
        "summary": {
            "total_products": len(changes),
            "auto_applied": auto_count,
            "pending_confirmation": pending_count,
            "skipped_insufficient_data": skipped_count,
        },
    }
    save_json(snapshot_file, snapshot)

    log = load_json(UPDATE_LOG_FILE)
    if not log:
        log = {"version": "1.0.0", "entries": []}
    log["entries"].append({
        "date": today,
        "trigger": trigger,
        "version": version,
        "auto_applied_count": auto_count,
        "pending_count": pending_count,
        "skipped_count": skipped_count,
        "history_file": str(snapshot_file.relative_to(BASE_DIR)),
    })
    save_json(UPDATE_LOG_FILE, log)
    return str(snapshot_file)


def apply_adaptive(baseline, proposal):
    """自动应用小幅变化，大幅变化写入待确认提案"""
    updated = dict(baseline)
    baselines = dict(updated.get("baselines", {}))
    pending = []
    applied = []

    for item in proposal.get("proposals", []):
        if item.get("auto_apply") and item.get("proposed_avg") is not None:
            key = item["baseline_key"]
            old = dict(baselines.get(key, {}))
            old["avg"] = item["proposed_avg"]
            old["source"] = "adaptive_auto"
            old["updated"] = today_str()
            baselines[key] = old
            applied.append(item)
        elif item.get("requires_confirmation"):
            pending.append(item)

    updated["baselines"] = baselines
    updated["updated_at"] = now_iso()

    if pending:
        pending_proposal = {
            "version": "2.0.0",
            "date": today_str(),
            "generated_at": now_iso(),
            "status": "pending_manual_confirmation",
            "proposals": pending,
        }
        save_json(PROPOSAL_FILE, pending_proposal)

    return updated, applied, pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["proposal", "adaptive", "apply-confirmed"],
                        default="proposal")
    parser.add_argument("--apply-confirmed", action="store_true", dest="legacy_apply")
    args = parser.parse_args()

    mode = args.mode
    if args.legacy_apply:
        mode = "apply-confirmed"

    baseline = load_json(BASELINE_FILE)

    if mode == "apply-confirmed":
        proposal = load_json(PROPOSAL_FILE)
        updated = apply_confirmed(baseline, proposal)
        save_json(BASELINE_FILE, updated)
        print(json.dumps({
            "ok": True, "mode": "apply_confirmed", "baseline": str(BASELINE_FILE),
        }, ensure_ascii=False, indent=2))
        return

    if mode == "adaptive":
        proposal = build_adaptive_proposal(baseline, TREND_HISTORY_DIR)
        snapshot_file = save_baseline_version(
            baseline, proposal.get("proposals", []), trigger="auto_weekly")
        updated, applied, pending = apply_adaptive(baseline, proposal)
        save_json(BASELINE_FILE, updated)
        print(json.dumps({
            "ok": True,
            "mode": "adaptive",
            "baseline": str(BASELINE_FILE),
            "snapshot": snapshot_file,
            "auto_applied": len(applied),
            "pending_confirmation": len(pending),
            "skipped": sum(1 for p in proposal.get("proposals", [])
                          if p.get("status") == "skipped_insufficient_data"),
        }, ensure_ascii=False, indent=2))
        return

    cache = load_json(PRICE_CACHE_FILE)
    proposal = build_proposal(baseline, cache)
    save_json(PROPOSAL_FILE, proposal)
    print(json.dumps({
        "ok": True, "mode": "proposal", "proposal": str(PROPOSAL_FILE),
        "items": len(proposal.get("proposals", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
