#!/usr/bin/env python3
"""
信号时效性判断规则
规则：
- 发布 <= 3天：保持原级别
- 发布 4-7天：降一级 (S -> A)
- 发布 > 7天：降两级 (S -> B)，不再作为高优信号推送
"""
from datetime import datetime

def evaluate_signal_level(event_date_str: str, base_level: str = "S") -> str:
    """
    根据事件发布日期评估当前信号级别
    
    Args:
        event_date_str: 事件发布日期，格式 YYYY-MM-DD
        base_level: 初始信号级别 (S/A/B/C)
    
    Returns:
        降级后的信号级别
    """
    event_date = datetime.strptime(event_date_str, "%Y-%m-%d")
    days_elapsed = (datetime.now() - event_date).days

    level_hierarchy = ["S", "A", "B", "C"]
    base_level = str(base_level or "B").replace("级", "")
    base_idx = level_hierarchy.index(base_level) if base_level in level_hierarchy else 2

    if days_elapsed <= 3:
        downgrade = 0
    elif days_elapsed <= 7:
        downgrade = 1
    else:
        downgrade = 2

    final_idx = min(base_idx + downgrade, len(level_hierarchy) - 1)
    return level_hierarchy[final_idx]


if __name__ == "__main__":
    # 测试：Pocket 4 发布于4月16日，今天27日 = 11天
    result = evaluate_signal_level("2026-04-16", "S")
    print(f"Pocket 4 信号级别: {result}")  # 应输出: B
