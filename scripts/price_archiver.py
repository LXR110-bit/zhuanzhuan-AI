#!/usr/bin/env python3
"""
价格历史归档脚本 (price_archiver.py)
功能：将每日价格快照保存到 trend_history 目录
调用时机：云电脑价格扫描任务完成后
"""

import json
import os
import sys
from datetime import datetime, timedelta

# 路径配置 - 相对于项目根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)  # scripts 的父目录
DATA_DIR = os.path.join(BASE_DIR, "data")
PRICE_CACHE = os.path.join(DATA_DIR, "price_cache.json")
TREND_HISTORY = os.path.join(DATA_DIR, "trend_history")
ARCHIVE_DAYS = 60  # 保留天数

PRICE_PATHS = [
    ("xianyu_market", "price"),
    ("xianyu_market", "median"),
    ("xianyu_market", "avg"),
    ("xianyu_market", "avg_price"),
    ("aihuishou", "base_price"),
    ("aihuishou", "after_coupon"),
    ("xianyu_official", "price"),
    ("aihuishou", "tansuo_price"),
]

def load_price_cache():
    """加载价格缓存文件"""
    if not os.path.exists(PRICE_CACHE):
        print(f"[归档] 价格缓存不存在: {PRICE_CACHE}")
        return None
    with open(PRICE_CACHE, 'r', encoding='utf-8') as f:
        return json.load(f)

def nested_get(data, path):
    cur = data
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur

def has_any_price(product_data):
    for path in PRICE_PATHS:
        value = nested_get(product_data, path)
        if value not in (None, "", "-", "—"):
            try:
                float(value)
                return True
            except (TypeError, ValueError):
                continue
    return False

def archive_daily_snapshot():
    """
    归档每日快照
    将 price_cache.json 中的各产品数据归档到对应目录
    """
    cache_data = load_price_cache()
    if not cache_data:
        return False
    
    today = cache_data.get('scan_time', datetime.now().strftime('%Y-%m-%d'))
    prices = cache_data.get('prices', {})
    
    archived_count = 0
    skipped_count = 0
    for product_id, product_data in prices.items():
        if not has_any_price(product_data):
            skipped_count += 1
            print(f"[归档] 跳过 {product_id}: 本次没有有效价格")
            continue
        # 确保产品目录存在
        product_dir = os.path.join(TREND_HISTORY, product_id)
        os.makedirs(product_dir, exist_ok=True)
        
        # 归档文件路径
        archive_file = os.path.join(product_dir, f"{today}.json")
        
        # 写入归档数据（包含时间戳）
        archive_data = {
            "archived_at": datetime.now().isoformat(),
            "scan_time": today,
            "product_id": product_id,
            "data": product_data
        }
        
        with open(archive_file, 'w', encoding='utf-8') as f:
            json.dump(archive_data, f, ensure_ascii=False, indent=2)
        
        archived_count += 1
        print(f"[归档] {product_id}: {today} -> {archive_file}")
    
    print(f"[归档] 完成，共归档 {archived_count} 个产品，跳过 {skipped_count} 个无有效价格产品")
    return True

def cleanup_old_archives():
    """
    清理过期归档
    保留最近 ARCHIVE_DAYS 天的数据
    """
    if not os.path.exists(TREND_HISTORY):
        return 0
    
    cutoff_date = datetime.now() - timedelta(days=ARCHIVE_DAYS)
    cutoff_str = cutoff_date.strftime('%Y-%m-%d')
    
    deleted_count = 0
    for product_id in os.listdir(TREND_HISTORY):
        product_dir = os.path.join(TREND_HISTORY, product_id)
        if not os.path.isdir(product_dir):
            continue
        
        for filename in os.listdir(product_dir):
            if not filename.endswith('.json'):
                continue
            if filename < cutoff_str:
                filepath = os.path.join(product_dir, filename)
                os.remove(filepath)
                deleted_count += 1
                print(f"[清理] 删除过期文件: {filepath}")
    
    if deleted_count > 0:
        print(f"[清理] 完成，共删除 {deleted_count} 个过期文件")
    return deleted_count

def get_price_history(product_id, days=7):
    """
    获取产品历史价格
    返回最近N天的价格数据列表
    """
    product_dir = os.path.join(TREND_HISTORY, product_id)
    if not os.path.exists(product_dir):
        return []
    
    history = []
    for filename in os.listdir(product_dir):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(product_dir, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            history.append({
                'date': filename.replace('.json', ''),
                'data': data['data']
            })
    
    # 按日期排序
    history.sort(key=lambda x: x['date'], reverse=True)
    return history[:days]

def generate_trend_report(product_id, days=7):
    """
    生成趋势分析报告
    """
    history = get_price_history(product_id, days)
    if not history:
        return f"暂无 {product_id} 的历史数据"
    
    report_lines = [f"## {product_id} 价格趋势报告 (近{days}天)", ""]
    report_lines.append("| 日期 | 回收价(探索加) | 闲鱼均价 | 趋势 |")
    report_lines.append("|------|---------------|----------|------|")
    
    for item in reversed(history):  # 从旧到新排列
        data = item['data']
        date = item['date']
        aihuishou_block = data.get('aihuishou', {})
        xianyu_block = data.get('xianyu_market', {})
        aihuishou = (
            aihuishou_block.get('tansuo_price')
            or aihuishou_block.get('base_price')
            or aihuishou_block.get('after_coupon')
            or 'N/A'
        )
        xianyu_avg = (
            xianyu_block.get('price')
            or xianyu_block.get('median')
            or xianyu_block.get('avg')
            or xianyu_block.get('avg_price')
            or 'N/A'
        )
        trend = data.get('trend', 'N/A')
        report_lines.append(f"| {date} | {aihuishou} | {xianyu_avg} | {trend} |")
    
    return "\n".join(report_lines)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "archive":
            archive_daily_snapshot()
        elif command == "cleanup":
            cleanup_old_archives()
        elif command == "report" and len(sys.argv) > 2:
            product_id = sys.argv[2]
            days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
            print(generate_trend_report(product_id, days))
        else:
            print("用法: python price_archiver.py [archive|cleanup|report <产品ID> [天数]]")
    else:
        # 默认执行归档
        archive_daily_snapshot()
