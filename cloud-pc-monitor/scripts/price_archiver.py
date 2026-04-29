#!/usr/bin/env python3
"""
价格归档脚本 - 保存每日价格快照到历史数据库
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

def archive_prices():
    """归档当前价格到历史数据库"""
    base_path = Path(__file__).resolve().parent.parent / "data"
    history_path = base_path / "trend_history"
    snapshot_path = base_path / "last_snapshot.json"
    
    if not snapshot_path.exists():
        print("No snapshot to archive")
        return False
    
    with open(snapshot_path, 'r', encoding='utf-8') as f:
        snapshot = json.load(f)
    
    scan_date = datetime.now().strftime("%Y-%m-%d")
    
    for model_id, data in snapshot.get('prices', {}).items():
        model_dir = history_path / model_id
        model_dir.mkdir(parents=True, exist_ok=True)
        
        history_file = model_dir / f"{scan_date}.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"Archived {len(snapshot.get('prices', {}))} models for {scan_date}")
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "archive":
        archive_prices()
    else:
        print("Usage: python3 price_archiver.py archive")
