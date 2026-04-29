#!/usr/bin/env python3
"""
云电脑价格扫描 - 增强版历史数据分析模块
功能：7天/30天价格对比、趋势分析、偏离度计算、连续涨跌检测、异动双重判断
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import statistics

# ============== 配置 ==============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(BASE_DIR, "data")
TREND_HISTORY = os.path.join(DATA_DIR, "trend_history")
PRICE_CACHE = os.path.join(DATA_DIR, "price_cache.json")

# 归档天数
ARCHIVE_DAYS = 60

# 分析参数
SHORT_TERM_DAYS = 7
MID_TERM_DAYS = 30
LONG_TERM_DAYS = 90

# 偏离度阈值
DEVIATION_WARNING = 10      # 偏离10%警告
DEVIATION_CRITICAL = 15    # 偏离15%严重

# 连续涨跌阈值
CONSECUTIVE_ALERT = 3      # 连续3天触发警告
CONSECUTIVE_CRITICAL = 5   # 连续5天触发严重

# 异动检测投票阈值
ANOMALY_POINT_MIN = 1      # 单点异常最少票数
ANOMALY_TREND_MIN = 1      # 趋势异常最少票数
S_LEVEL_POINT = 2          # S级单点票数
S_LEVEL_TREND = 1          # S级趋势票数

# ============== 工具函数 ==============

def load_json(filepath: str) -> Optional[Dict]:
    """加载JSON文件"""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[错误] 加载 {filepath} 失败: {e}")
        return None

def get_date_list(days: int) -> List[str]:
    """获取最近N天的日期列表"""
    today = datetime.now()
    return [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)]

def get_price_value(data: Dict, price_type: str = "aihuishou") -> Optional[float]:
    """从产品数据中提取价格"""
    if price_type == "aihuishou":
        return data.get("aihuishou", {}).get("tansuo_price")
    elif price_type == "xianyu_avg":
        return data.get("xianyu_market", {}).get("avg")
    elif price_type == "official":
        return data.get("official")
    return None

# ============== 核心分析函数 ==============

def load_archive(product_id: str, date: str) -> Optional[Dict]:
    """加载指定产品的指定日期归档"""
    archive_file = os.path.join(TREND_HISTORY, product_id, f"{date}.json")
    if os.path.exists(archive_file):
        data = load_json(archive_file)
        return data.get("data") if data else None
    return None

def load_recent_archives(product_id: str, days: int = 30) -> List[Dict]:
    """加载最近N天的归档数据"""
    dates = get_date_list(days)
    archives = []
    
    for date in dates:
        data = load_archive(product_id, date)
        if data:
            archives.append({
                "date": date,
                "data": data
            })
    
    # 按日期正序（旧 -> 新）。趋势、动量和异常检测都以最后一个价格作为当前价。
    archives.sort(key=lambda x: x["date"])
    return archives

def calculate_change(current: float, baseline: float) -> Dict:
    """计算涨跌幅"""
    if baseline == 0 or baseline is None:
        return {
            "change_amount": None,
            "change_pct": None,
            "direction": "unknown",
            "severity": "unknown"
        }
    
    change_amount = current - baseline
    change_pct = (change_amount / baseline) * 100
    
    if abs(change_pct) < 0.5:
        direction = "stable"
    elif change_pct > 0:
        direction = "up"
    else:
        direction = "down"
    
    # 严重程度判断
    abs_pct = abs(change_pct)
    if abs_pct < 3:
        severity = "minor"
    elif abs_pct < 5:
        severity = "moderate"
    elif abs_pct < 10:
        severity = "significant"
    else:
        severity = "drastic"
    
    return {
        "change_amount": round(change_amount, 2),
        "change_pct": round(change_pct, 2),
        "direction": direction,
        "severity": severity
    }

def get_historical_comparison(product_id: str, price_type: str = "aihuishou") -> Dict:
    """获取多周期历史对比"""
    today = datetime.now().strftime('%Y-%m-%d')
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    month_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    # 获取各时期数据
    current_data = load_archive(product_id, today)
    week_data = load_archive(product_id, week_ago)
    month_data = load_archive(product_id, month_ago)
    
    current_price = get_price_value(current_data, price_type) if current_data else None
    week_price = get_price_value(week_data, price_type) if week_data else None
    month_price = get_price_value(month_data, price_type) if month_data else None
    
    # 计算涨跌幅
    week_change = calculate_change(current_price, week_price) if current_price and week_price else {}
    month_change = calculate_change(current_price, month_price) if current_price and month_price else {}
    
    return {
        "product_id": product_id,
        "price_type": price_type,
        "current": {"price": current_price, "date": today},
        "7day_ago": {"price": week_price, "date": week_ago},
        "30day_ago": {"price": month_price, "date": month_ago},
        "7day_change_pct": week_change.get("change_pct"),
        "30day_change_pct": month_change.get("change_pct"),
        "7day_change": week_change,
        "30day_change": month_change
    }

def calculate_trend(prices: List[float], dates: List[str] = None) -> Dict:
    """计算价格趋势（线性回归增强版）"""
    if len(prices) < 2:
        return {
            "trend": "insufficient_data",
            "slope": 0,
            "change_pct": 0,
            "avg": None,
            "min": None,
            "max": None
        }
    
    n = len(prices)
    x = list(range(n))
    x_mean = statistics.mean(x)
    y_mean = statistics.mean(prices)
    
    # 线性回归斜率
    numerator = sum((x[i] - x_mean) * (prices[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
    slope = numerator / denominator if denominator != 0 else 0
    
    # 总变化百分比
    if prices[0] != 0:
        change_pct = (prices[-1] - prices[0]) / prices[0] * 100
    else:
        change_pct = 0
    
    # 趋势方向
    if abs(slope) < 1:
        direction = "stable"
    elif slope > 0:
        direction = "rising"
    else:
        direction = "falling"
    
    return {
        "trend": direction,
        "slope": round(slope, 2),
        "change_pct": round(change_pct, 2),
        "avg": round(statistics.mean(prices), 2),
        "min": round(min(prices), 2),
        "max": round(max(prices), 2),
        "sample_count": n
    }

def analyze_trend(product_id: str, price_type: str = "aihuishou", days: int = 30) -> Dict:
    """分析产品趋势（综合分析）"""
    archives = load_recent_archives(product_id, days)
    
    if len(archives) < 2:
        return {
            "product_id": product_id,
            "status": "insufficient_data",
            "message": f"历史数据不足（仅{len(archives)}天）"
        }
    
    # 提取价格序列
    prices = []
    dates = []
    for archive in archives:
        price = get_price_value(archive["data"], price_type)
        if price:
            prices.append(price)
            dates.append(archive["date"])
    
    if len(prices) < 2:
        return {
            "product_id": product_id,
            "status": "no_price_data"
        }
    
    # 基础趋势分析
    trend_info = calculate_trend(prices, dates)
    
    # 连续涨跌检测
    consecutive = detect_consecutive_trend(prices)
    
    # 动量分析（加速/减速）
    momentum = analyze_momentum(prices)
    
    # 计算动量（0-1）
    momentum_score = min(abs(trend_info["change_pct"]) / 20, 1.0) if trend_info["change_pct"] != 0 else 0
    
    return {
        "product_id": product_id,
        "price_type": price_type,
        "trend": trend_info["trend"],
        "slope": trend_info["slope"],              # 每日平均变化
        "change_pct": trend_info["change_pct"],   # 总体变化百分比
        "consecutive_days": consecutive["current_streak"],
        "consecutive_direction": consecutive["direction"],
        "acceleration": momentum["signal"],
        "momentum": round(momentum_score, 2),
        "week_changes": momentum["weekly_changes"],
        "period_days": len(prices)
    }

def detect_consecutive_trend(prices: List[float]) -> Dict:
    """检测连续涨跌趋势"""
    if len(prices) < 3:
        return {
            "current_streak": 0,
            "direction": "unknown",
            "max_streak": 0
        }
    
    # 计算日变化方向
    changes = []
    for i in range(1, len(prices)):
        if prices[i-1] != 0:
            pct_change = (prices[i] - prices[i-1]) / prices[i-1] * 100
            if pct_change > 0.5:
                changes.append("up")
            elif pct_change < -0.5:
                changes.append("down")
            else:
                changes.append("stable")
    
    # 统计连续同向
    max_streak = 0
    current_streak = 0
    streak_direction = None
    max_streak_dir = None
    
    for change in changes:
        if change == streak_direction and change != "stable":
            current_streak += 1
        else:
            if current_streak > max_streak:
                max_streak = current_streak
                max_streak_dir = streak_direction
            current_streak = 1 if change != "stable" else 0
            streak_direction = change
    
    if current_streak > max_streak:
        max_streak = current_streak
        max_streak_dir = streak_direction
    
    return {
        "current_streak": current_streak,
        "direction": streak_direction if streak_direction != "stable" else "stable",
        "max_streak": max_streak,
        "max_streak_direction": max_streak_dir
    }

def analyze_momentum(prices: List[float]) -> Dict:
    """分析涨跌加速/减速信号"""
    if len(prices) < 8:
        return {"signal": "insufficient_data", "weekly_changes": []}
    
    # 按周分段（每7天一组）
    weekly_changes = []
    weeks = (len(prices) - 1) // 7
    
    for w in range(min(weeks, 4)):  # 最多4周
        start_idx = w * 7
        end_idx = min((w + 1) * 7, len(prices) - 1)
        if end_idx > start_idx and prices[start_idx] != 0:
            week_change = (prices[end_idx] - prices[start_idx]) / prices[start_idx] * 100
            weekly_changes.append(round(week_change, 2))
    
    if len(weekly_changes) < 2:
        return {"signal": "insufficient_data", "weekly_changes": weekly_changes}
    
    # 判断加速/减速
    latest = weekly_changes[-1]  # 最近一周
    previous = statistics.mean(weekly_changes[:-1]) if len(weekly_changes) > 1 else 0
    
    if abs(latest) > abs(previous) * 1.2:
        signal = "accelerating"
    elif abs(latest) < abs(previous) * 0.8:
        signal = "slowing"
    else:
        signal = "stable"
    
    # 预测下周（基于最近趋势）
    if len(weekly_changes) >= 2:
        # 使用最近2周平均变化作为下周预测
        forecast = statistics.mean(weekly_changes[-2:])
    else:
        forecast = weekly_changes[0] if weekly_changes else 0
    
    return {
        "signal": signal,
        "weekly_changes": weekly_changes,
        "latest_week_change": round(latest, 2) if weekly_changes else None,
        "forecast_next_week": round(forecast, 2)
    }

def calculate_deviation(product_id: str, price_type: str = "aihuishou") -> Dict:
    """计算当前价偏离历史均值"""
    archives_7 = load_recent_archives(product_id, 7)
    archives_30 = load_recent_archives(product_id, 30)
    
    prices_7 = []
    prices_30 = []
    current_price = None
    
    # 7天数据
    for archive in archives_7:
        price = get_price_value(archive["data"], price_type)
        if price:
            if archive["date"] == datetime.now().strftime('%Y-%m-%d'):
                current_price = price
            prices_7.append(price)
    
    # 30天数据
    for archive in archives_30:
        price = get_price_value(archive["data"], price_type)
        if price:
            if current_price is None and archive["date"] == datetime.now().strftime('%Y-%m-%d'):
                current_price = price
            prices_30.append(price)
    
    if current_price is None or (not prices_7 and not prices_30):
        return {"status": "insufficient_data"}
    
    avg_7 = statistics.mean(prices_7) if prices_7 else None
    avg_30 = statistics.mean(prices_30) if prices_30 else None
    
    deviation_7 = ((current_price - avg_7) / avg_7 * 100) if avg_7 else None
    deviation_30 = ((current_price - avg_30) / avg_30 * 100) if avg_30 else None
    
    return {
        "product_id": product_id,
        "current_price": current_price,
        "7day_avg": round(avg_7, 2) if avg_7 else None,
        "30day_avg": round(avg_30, 2) if avg_30 else None,
        "deviation_7day_pct": round(deviation_7, 2) if deviation_7 else None,
        "deviation_30day_pct": round(deviation_30, 2) if deviation_30 else None,
        "is_undervalued": deviation_30 is not None and deviation_30 < -DEVIATION_WARNING,
        "is_oversold": deviation_7 is not None and deviation_7 < -DEVIATION_WARNING,
        "is_overvalued": deviation_30 is not None and deviation_30 > DEVIATION_WARNING
    }

# ============== 异动检测（双重判断）==============

def _detect_zscore(prices: List[float], threshold: float = 2.0) -> bool:
    """Z-score 检测"""
    if len(prices) < 3:
        return False
    mean = statistics.mean(prices)
    stdev = statistics.stdev(prices) if len(prices) > 1 else 0
    if stdev == 0:
        return False
    return abs((prices[-1] - mean) / stdev) > threshold

def _detect_iqr(prices: List[float], factor: float = 1.5) -> bool:
    """IQR 检测"""
    if len(prices) < 4:
        return False
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    q1 = sorted_prices[n // 4]
    q3 = sorted_prices[3 * n // 4]
    iqr = q3 - q1
    lower = q1 - factor * iqr
    upper = q3 + factor * iqr
    return prices[-1] < lower or prices[-1] > upper

def _detect_percentile(prices: List[float], low: int = 5, high: int = 95) -> bool:
    """百分位检测"""
    if len(prices) < 5:
        return False
    sorted_prices = sorted(prices)
    n = len(sorted_prices)
    p_low = sorted_prices[int(n * low / 100)]
    p_high = sorted_prices[int(n * high / 100)]
    return prices[-1] < p_low or prices[-1] > p_high

def _detect_moving_avg(prices: List[float], window: int = 3, threshold: float = 0.15) -> bool:
    """移动平均检测"""
    if len(prices) < window + 1:
        return False
    avg = statistics.mean(prices[-window-1:-1])
    if avg == 0:
        return False
    return abs(prices[-1] - avg) / avg > threshold

def _check_deviation_anomaly(deviation: Dict) -> bool:
    """偏离度异常检测"""
    if deviation.get("status") == "insufficient_data":
        return False
    dev_30 = deviation.get("deviation_30day_pct")
    return dev_30 is not None and abs(dev_30) > DEVIATION_CRITICAL

def _check_consecutive_anomaly(trend: Dict) -> bool:
    """连续涨跌异常检测"""
    consecutive = trend.get("consecutive_days", 0)
    return consecutive >= CONSECUTIVE_CRITICAL

def _check_slope_anomaly(prices: List[float], threshold: float = 0.1) -> bool:
    """斜率突变检测"""
    if len(prices) < 10:
        return False
    # 对比前半段和后半段的斜率
    mid = len(prices) // 2
    first_half = prices[mid:]
    second_half = prices[:mid]
    
    if len(first_half) < 3 or len(second_half) < 3:
        return False
    
    trend1 = calculate_trend(first_half)
    trend2 = calculate_trend(second_half)
    
    # 方向反转或斜率变化超过阈值
    if trend1["trend"] != trend2["trend"] and trend1["trend"] != "stable" and trend2["trend"] != "stable":
        return True
    
    if abs(trend1["slope"] - trend2["slope"]) > threshold * max(abs(trend1["slope"]), abs(trend2["slope"])):
        return True
    
    return False

def _check_acceleration_anomaly(momentum: Dict) -> bool:
    """加速信号异常检测"""
    if momentum.get("signal") == "accelerating":
        return True
    return False

def detect_enhanced_anomaly(product_id: str, price_type: str = "aihuishou") -> Dict:
    """增强版异动检测（单点+趋势双重判断）"""
    archives = load_recent_archives(product_id, 30)
    
    # 提取价格序列
    prices = []
    dates = []
    for archive in archives:
        price = get_price_value(archive["data"], price_type)
        if price:
            prices.append(price)
            dates.append(archive["date"])
    
    if len(prices) < 5:
        return {
            "status": "insufficient_data",
            "message": f"数据不足（{len(prices)}条）"
        }
    
    results = {
        "product_id": product_id,
        "analyzed_at": datetime.now().isoformat(),
        "point_anomaly": {
            "detected": False,
            "methods": [],
            "severity": 0
        },
        "trend_anomaly": {
            "detected": False,
            "methods": [],
            "severity": 0
        },
        "final_level": None,
        "action": None,
        "details": {}
    }
    
    # 单点异常检测
    point_methods = [
        ("zscore", _detect_zscore(prices)),
        ("iqr", _detect_iqr(prices)),
        ("percentile", _detect_percentile(prices)),
        ("moving_avg", _detect_moving_avg(prices))
    ]
    
    for method_name, detected in point_methods:
        if detected:
            results["point_anomaly"]["detected"] = True
            results["point_anomaly"]["methods"].append(method_name)
            results["point_anomaly"]["severity"] += 1
    
    # 趋势异常检测 - 需要额外数据
    deviation = calculate_deviation(product_id, price_type)
    trend_info = analyze_trend(product_id, price_type, 30)
    momentum = analyze_momentum(prices)
    
    trend_methods = [
        ("deviation", _check_deviation_anomaly(deviation)),
        ("consecutive", _check_consecutive_anomaly(trend_info)),
        ("slope_change", _check_slope_anomaly(prices)),
        ("acceleration", _check_acceleration_anomaly(momentum))
    ]
    
    for method_name, detected in trend_methods:
        if detected:
            results["trend_anomaly"]["detected"] = True
            results["trend_anomaly"]["methods"].append(method_name)
            results["trend_anomaly"]["severity"] += 1
    
    # 判定最终级别
    point_sev = results["point_anomaly"]["severity"]
    trend_sev = results["trend_anomaly"]["severity"]
    
    if point_sev >= S_LEVEL_POINT and trend_sev >= S_LEVEL_TREND:
        results["final_level"] = "S"
        results["action"] = "立即推送"
    elif point_sev >= 1 and trend_sev >= 2:
        results["final_level"] = "A"
        results["action"] = "24h内推送"
    elif point_sev >= 1:
        results["final_level"] = "B"
        results["action"] = "加入监控"
    elif trend_sev >= 1:
        results["final_level"] = "C"
        results["action"] = "日报汇总"
    else:
        results["final_level"] = "N"
        results["action"] = "无异常"
    
    results["details"] = {
        "deviation": deviation,
        "trend": trend_info,
        "momentum": momentum
    }
    
    return results

# ============== 批量分析与报告 ==============

def analyze_product_full(product_id: str, price_type: str = "aihuishou") -> Dict:
    """单个产品完整分析"""
    return {
        "product_id": product_id,
        "analyzed_at": datetime.now().isoformat(),
        "price_comparison": get_historical_comparison(product_id, price_type),
        "trend_analysis": analyze_trend(product_id, price_type),
        "deviation": calculate_deviation(product_id, price_type),
        "anomaly_detection": detect_enhanced_anomaly(product_id, price_type)
    }

def scan_all_products(price_type: str = "aihuishou") -> Dict:
    """扫描所有产品"""
    if not os.path.exists(TREND_HISTORY):
        return {"status": "no_data", "message": "无历史数据目录"}
    
    products = [d for d in os.listdir(TREND_HISTORY) 
                if os.path.isdir(os.path.join(TREND_HISTORY, d))]
    
    results = {
        "scanned_at": datetime.now().isoformat(),
        "total_products": len(products),
        "products": {},
        "summary": {
            "total_anomalies": 0,
            "level_s": 0,
            "level_a": 0,
            "level_b": 0,
            "level_c": 0,
            "normal": 0,
            "rising": 0,
            "falling": 0,
            "stable": 0
        }
    }
    
    for product in products:
        analysis = analyze_product_full(product, price_type)
        results["products"][product] = analysis
        
        # 汇总统计
        anomaly = analysis.get("anomaly_detection", {})
        level = anomaly.get("final_level", "N")
        if level == "S":
            results["summary"]["level_s"] += 1
            results["summary"]["total_anomalies"] += 1
        elif level == "A":
            results["summary"]["level_a"] += 1
            results["summary"]["total_anomalies"] += 1
        elif level == "B":
            results["summary"]["level_b"] += 1
            results["summary"]["total_anomalies"] += 1
        elif level == "C":
            results["summary"]["level_c"] += 1
        else:
            results["summary"]["normal"] += 1
        
        trend = analysis.get("trend_analysis", {}).get("trend", "unknown")
        if trend == "rising":
            results["summary"]["rising"] += 1
        elif trend == "falling":
            results["summary"]["falling"] += 1
        elif trend == "stable":
            results["summary"]["stable"] += 1
    
    return results

def generate_report(analysis: Dict) -> str:
    """生成格式化报告"""
    product_id = analysis.get("product_id", "Unknown")
    
    lines = [
        f"# {product_id} 历史分析报告",
        f"生成时间：{analysis.get('analyzed_at', 'N/A')}",
        "",
        "## 📊 价格对比",
        ""
    ]
    
    # 价格对比
    comparison = analysis.get("price_comparison", {})
    if comparison.get("current", {}).get("price"):
        lines.append(f"- 当前价格：**¥{comparison['current']['price']}** ({comparison['current']['date']})")
        if comparison.get("7day_change_pct") is not None:
            pct = comparison["7day_change_pct"]
            arrow = "📈" if pct > 0 else "📉"
            lines.append(f"- 7天变化：{arrow} {pct:+.2f}%")
        if comparison.get("30day_change_pct") is not None:
            pct = comparison["30day_change_pct"]
            arrow = "📈" if pct > 0 else "📉"
            lines.append(f"- 30天变化：{arrow} {pct:+.2f}%")
    
    # 趋势分析
    trend = analysis.get("trend_analysis", {})
    if trend.get("status") != "insufficient_data":
        lines.extend([
            "",
            "## 📈 趋势分析",
            ""
        ])
        if trend.get("trend"):
            trend_icon = {"rising": "📈", "falling": "📉", "stable": "➡️"}.get(trend["trend"], "❓")
            lines.append(f"- 趋势方向：{trend_icon} {trend.get('trend', 'N/A').upper()}")
        if trend.get("slope") is not None:
            lines.append(f"- 日均变化：{trend['slope']:+.2f}")
        if trend.get("consecutive_days", 0) > 0:
            direction_text = {
                "up": "上涨",
                "down": "下跌",
                "stable": "持平",
                "unknown": "变化"
            }.get(trend.get("consecutive_direction", "unknown"), "变化")
            lines.append(f"- 连续{direction_text}：{trend['consecutive_days']}天")
        if trend.get("acceleration"):
            lines.append(f"- 动量信号：{trend['acceleration']}")
    
    # 偏离度
    deviation = analysis.get("deviation", {})
    if deviation.get("current_price"):
        lines.extend([
            "",
            "## 📏 偏离度分析",
            ""
        ])
        lines.append(f"- 当前价格：¥{deviation['current_price']}")
        if deviation.get("7day_avg"):
            lines.append(f"- 7日均值：¥{deviation['7day_avg']}")
            lines.append(f"- 偏离7日均值：{deviation.get('deviation_7day_pct', 0):+.2f}%")
        if deviation.get("30day_avg"):
            lines.append(f"- 30日均值：¥{deviation['30day_avg']}")
            lines.append(f"- 偏离30日均值：{deviation.get('deviation_30day_pct', 0):+.2f}%")
        
        if deviation.get("is_undervalued"):
            lines.append("- 💡 当前价格被**低估**")
        if deviation.get("is_overvalued"):
            lines.append("- ⚠️ 当前价格被**高估**")
    
    # 异动检测
    anomaly = analysis.get("anomaly_detection", {})
    if anomaly.get("status") != "insufficient_data":
        lines.extend([
            "",
            "## 🚨 异动检测",
            ""
        ])
        level = anomaly.get("final_level", "N")
        level_icon = {"S": "🔴", "A": "🟠", "B": "🟡", "C": "🟢", "N": "⚪"}.get(level, "⚪")
        lines.append(f"- 异动级别：{level_icon} **级** ({level})")
        lines.append(f"- 建议操作：{anomaly.get('action', 'N/A')}")
        
        if anomaly.get("point_anomaly", {}).get("methods"):
            lines.append(f"- 单点异常：{', '.join(anomaly['point_anomaly']['methods'])}")
        if anomaly.get("trend_anomaly", {}).get("methods"):
            lines.append(f"- 趋势异常：{', '.join(anomaly['trend_anomaly']['methods'])}")
    
    return "\n".join(lines)

# ============== 主程序 ==============

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 price_history_analyzer.py compare <产品ID>    # 价格对比")
        print("  python3 price_history_analyzer.py trend <产品ID>      # 趋势分析")
        print("  python3 price_history_analyzer.py anomaly <产品ID>    # 异动检测")
        print("  python3 price_history_analyzer.py full <产品ID>       # 完整分析")
        print("  python3 price_history_analyzer.py scan-all            # 扫描所有产品")
        print("  python3 price_history_analyzer.py report <产品ID>      # 生成报告")
        return
    
    command = sys.argv[1]
    
    if command == "compare" and len(sys.argv) > 2:
        result = get_historical_comparison(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif command == "trend" and len(sys.argv) > 2:
        result = analyze_trend(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif command == "anomaly" and len(sys.argv) > 2:
        result = detect_enhanced_anomaly(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif command == "deviation" and len(sys.argv) > 2:
        result = calculate_deviation(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif command == "full" and len(sys.argv) > 2:
        result = analyze_product_full(sys.argv[2])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif command == "scan-all":
        result = scan_all_products()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    elif command == "report" and len(sys.argv) > 2:
        analysis = analyze_product_full(sys.argv[2])
        print(generate_report(analysis))
    
    else:
        print(f"[错误] 未知命令或参数不足: {command}")


if __name__ == "__main__":
    main()
