#!/usr/bin/env python3
"""
每日数据备份脚本
将当天所有价格数据、日报、执行状态打包备份
"""
import os
import json
import shutil
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = BASE_DIR / "每日备份"

def backup_daily_data():
    """备份当天所有数据"""
    today = datetime.now().strftime("%Y-%m-%d")
    backup_path = BACKUP_DIR / today
    
    # 创建备份目录
    backup_path.mkdir(parents=True, exist_ok=True)
    
    backup_files = []
    
    # 1. 价格数据
    price_files = [
        "price_cache.json",
        "daily_report_payload.json",
        "progress.json",
        "push_status.json",
        "daytime_scan_status.json",
        "validation_report.json",
        "anomaly_votes.json",
        "latest.json",
    ]
    
    for f in price_files:
        src = DATA_DIR / f
        if src.exists():
            shutil.copy2(src, backup_path / f)
            backup_files.append(f)
    
    # 2. 今日价格记录
    daily_record = DATA_DIR / "daily_price_records" / f"{today}.json"
    if daily_record.exists():
        shutil.copy2(daily_record, backup_path / f"daily_price_record_{today}.json")
        backup_files.append(f"daily_price_record_{today}.json")
    
    # 3. 今日价格扫描文件
    for f in DATA_DIR.glob(f"prices_{today.replace('-', '')}*.json"):
        shutil.copy2(f, backup_path / f.name)
        backup_files.append(f.name)
    
    # 4. 日报图片和payload
    periodic_dir = DATA_DIR / "periodic_reports"
    if periodic_dir.exists():
        for f in periodic_dir.glob(f"{today}*"):
            shutil.copy2(f, backup_path / f.name)
            backup_files.append(f.name)
    
    # 5. 写入备份清单
    manifest = {
        "backup_date": today,
        "backup_time": datetime.now().isoformat(),
        "files": sorted(backup_files),
        "total_files": len(backup_files)
    }
    
    with open(backup_path / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    
    return manifest

if __name__ == "__main__":
    manifest = backup_daily_data()
    print(f"✅ 备份完成: {manifest['total_files']} 个文件")
    print(f"📁 路径: 每日备份/{manifest['backup_date']}/")
