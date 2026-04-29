#!/usr/bin/env python3
"""
量价场景判断模块
功能：根据回收量、估价UV、价格变化判断市场场景
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.thresholds_v2 import (
    VOLUME_PRICE_THRESHOLDS, 
    PANIC_THRESHOLDS, 
    SUPPLY_DEMAND_THRESHOLDS
)


class MarketScenario(Enum):
    NORMAL_GROWTH = "量价齐升：健康增长"
    REPLACEMENT_DEMAND = "量升价跌：换机需求"
    SUPPLY_EXCESS = "量升价跌：供给过剩"
    DEMAND_SHRINK = "量跌价升：需求收缩"
    PANIC_SELL = "量价齐跌：恐慌抛售"
    SUPPLY_SHOCK = "供给侧冲击"
    DEMAND_SHOCK = "需求侧冲击"


@dataclass
class VolumePriceInput:
    volume_change_pct: float     # 回收量变化 %
    uv_change_pct: float         # 估价UV变化 %
    price_change_pct: float      # 价格变化 %
    supply_ratio: float = 1.0    # 供给量/正常水平
    demand_ratio: float = 1.0    # 需求量/正常水平


@dataclass
class ScenarioResult:
    scenario: MarketScenario
    risk_level: str              # "low" | "medium" | "high" | "critical"
    price_action: str            # 建议价格动作
    procurement_action: str      # 建议采购动作
    confidence: float            # 判断置信度 0-1


def judge_scenario(vp: VolumePriceInput) -> ScenarioResult:
    """
    判断市场场景
    
    关键洞察（来自业务反馈）：
    - 回收量涨 + 估价UV涨 + 价格跌 = 换机需求（正常）
    - 回收量暴涨后暴跌 + 价格大跌 = 恐慌抛售（风险）
    """
    v = vp.volume_change_pct
    u = vp.uv_change_pct
    p = vp.price_change_pct
    s = vp.supply_ratio
    d = vp.demand_ratio
    
    t = VOLUME_PRICE_THRESHOLDS
    pt = PANIC_THRESHOLDS
    sdt = SUPPLY_DEMAND_THRESHOLDS
    
    # 供给侧冲击：供给量异常飙升
    if s >= sdt["supply_shock_ratio"]:
        return ScenarioResult(
            MarketScenario.SUPPLY_SHOCK,
            "high",
            "下调收购价5-15%",
            "降低收购价格，减少收购量",
            0.85,
        )
    
    # 需求侧冲击：需求量异常萎缩
    if d <= sdt["demand_collapse_ratio"]:
        return ScenarioResult(
            MarketScenario.DEMAND_SHOCK,
            "high",
            "降价8-12%刺激需求",
            "暂停新增采购",
            0.85,
        )
    
    # 量升 + 价跌 + UV升 = 换机需求（关键洞察）
    if v >= t["volume_up"] and p <= t["price_down"] and u >= t["volume_up"]:
        return ScenarioResult(
            MarketScenario.REPLACEMENT_DEMAND,
            "low",
            "维持或小幅上调收购价",
            "积极收货，市场健康",
            0.90,
        )
    
    # 量升 + 价跌 + UV平/跌 = 供给过剩
    if v >= t["volume_up"] and p <= t["price_down"] and u < t["volume_up"]:
        return ScenarioResult(
            MarketScenario.SUPPLY_EXCESS,
            "medium",
            "暂停降价，观察3天",
            "降低收购价5-10%",
            0.78,
        )
    
    # 恐慌抛售：量价齐跌 + 跌幅剧烈
    if (v <= pt["volume_drop"] and p <= pt["price_drop"]):
        return ScenarioResult(
            MarketScenario.PANIC_SELL,
            "critical",
            "立即停止降价，等待市场稳定",
            "全面暂停采购，启动止损",
            0.90,
        )
    
    # 量价齐跌（轻度）
    if v <= t["volume_down"] and p <= t["price_down"]:
        return ScenarioResult(
            MarketScenario.PANIC_SELL,
            "medium",
            "小幅降价3-5%试探需求",
            "减少采购量30%",
            0.70,
        )
    
    # 量跌价升
    if v <= t["volume_down"] and p >= t["price_up"]:
        return ScenarioResult(
            MarketScenario.DEMAND_SHRINK,
            "medium",
            "维持价格，不跟涨",
            "维持采购，等待需求回升",
            0.75,
        )
    
    # 量价齐升
    if v >= t["volume_up"] and p >= t["price_up"]:
        return ScenarioResult(
            MarketScenario.NORMAL_GROWTH,
            "low",
            "跟随市场小幅上调",
            "维持当前采购节奏",
            0.80,
        )
    
    # 默认：正常
    return ScenarioResult(
        MarketScenario.NORMAL_GROWTH,
        "low",
        "维持现价",
        "正常运营",
        0.50,
    )


if __name__ == "__main__":
    # 测试：Pocket 3 换机需求场景
    vp = VolumePriceInput(
        volume_change_pct=0.20,   # 回收量涨20%
        uv_change_pct=0.30,       # UV涨30%
        price_change_pct=-0.08,   # 价格跌8%
    )
    result = judge_scenario(vp)
    print(f"场景: {result.scenario.value}")
    print(f"风险: {result.risk_level}")
    print(f"建议: {result.price_action}")
