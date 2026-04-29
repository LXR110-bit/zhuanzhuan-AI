#!/usr/bin/env python3
"""Create or apply weekly baseline update proposals.

Default mode is safe: it writes a proposal for manual confirmation and does
not change config/baseline.json.
"""
import argparse
import json
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
BASELINE_FILE = CONFIG_DIR / "baseline.json"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
PROPOSAL_FILE = DATA_DIR / "baseline_update_proposal.json"


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-confirmed", action="store_true")
    args = parser.parse_args()

    baseline = load_json(BASELINE_FILE)
    if args.apply_confirmed:
        proposal = load_json(PROPOSAL_FILE)
        updated = apply_confirmed(baseline, proposal)
        save_json(BASELINE_FILE, updated)
        print(json.dumps({
            "ok": True,
            "mode": "apply_confirmed",
            "baseline": str(BASELINE_FILE),
        }, ensure_ascii=False, indent=2))
        return

    cache = load_json(PRICE_CACHE_FILE)
    proposal = build_proposal(baseline, cache)
    save_json(PROPOSAL_FILE, proposal)
    print(json.dumps({
        "ok": True,
        "mode": "proposal",
        "proposal": str(PROPOSAL_FILE),
        "items": len(proposal.get("proposals", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
