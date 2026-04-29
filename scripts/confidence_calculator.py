#!/usr/bin/env python3
"""置信度计算与异动检测模块"""
import json
from datetime import datetime

# 搜索结果数据
search_results = {
    "RTX_3070": {"current_min": 3899, "current_max": 4999, "current_avg": 4449, "sources": 3, "data_points": 5},
    "RTX_3090": {"current_min": 12999, "current_max": 18999, "current_avg": 15999, "sources": 3, "data_points": 4},
    "RTX_4060": {"current_min": 2299, "current_max": 2499, "current_avg": 2399, "sources": 2, "data_points": 4},
    "RTX_4070": {"current_min": 4799, "current_max": 4999, "current_avg": 4899, "sources": 2, "data_points": 3},
    "RTX_4080": {"current_min": 9900, "current_max": 9900, "current_avg": 9900, "sources": 2, "data_points": 2},
    "RX_6600": {"current_min": 2499, "current_max": 2499, "current_avg": 2499, "sources": 2, "data_points": 3},
    "RX_7600": {"current_min": 1399, "current_max": 1729, "current_avg": 1564, "sources": 2, "data_points": 3},
    "Pocket_3": {"current_min": 2499, "current_max": 2799, "current_avg": 2649, "sources": 4, "data_points": 6},
    "Pocket_2": {"current_min": 1999, "current_max": 1999, "current_avg": 1999, "sources": 2, "data_points": 2},
    "Action_4": {"current_min": 1398, "current_max": 1398, "current_avg": 1398, "sources": 3, "data_points": 4},
    "Action_5_Pro": {"current_min": 2098, "current_max": 2098, "current_avg": 2098, "sources": 2, "data_points": 2},
    "Insta360_X4": {"current_min": 2999, "current_max": 2999, "current_avg": 2999, "sources": 3, "data_points": 4},
    "Insta360_X5": {"current_min": 2798, "current_max": 2798, "current_avg": 2798, "sources": 3, "data_points": 4},
    "Insta360_X3": {"current_min": 1398, "current_max": 2299, "current_avg": 1848, "sources": 2, "data_points": 3},
    "GoPro_11": {"current_min": 998, "current_max": 2698, "current_avg": 1848, "sources": 3, "data_points": 5},
    "GoPro_12": {"current_min": 1708, "current_max": 2148, "current_avg": 1928, "sources": 3, "data_points": 4},
    "DJI_Mini_3": {"current_min": 2088, "current_max": 2088, "current_avg": 2088, "sources": 2, "data_points": 3},
    "DJI_Mini_4": {"current_min": 1699, "current_max": 1699, "current_avg": 1699, "sources": 2, "data_points": 2},
    "DDR5_16G": {"current_min": 550, "current_max": 700, "current_avg": 625, "sources": 4, "data_points": 6},
    "DDR5_32G": {"current_min": 599, "current_max": 759, "current_avg": 679, "sources": 3, "data_points": 5},
    "i5_13600K": {"current_min": 1899, "current_max": 1999, "current_avg": 1949, "sources": 3, "data_points": 4},
    "i7_13700K": {"current_min": 2699, "current_max": 2899, "current_avg": 2799, "sources": 3, "data_points": 4},
}

# Baseline数据
baselines = {
    "RTX_3070": {"min": 3899, "max": 4999, "avg": 4299},
    "RTX_3090": {"min": 12999, "max": 18999, "avg": 15999},
    "RTX_4060": {"min": 2299, "max": 2899, "avg": 2549},
    "RX_6600": {"min": 2499, "max": 3499, "avg": 2849},
    "i7_13700K": {"min_eur": 400, "max_eur": 420, "avg_eur": 410},
    "DDR5_16G": {"min": 550, "max": 600, "avg": 575},
    "DDR5_32G": {"min": 1000, "max": 1500, "avg": 1200},
    "Pocket_3": {"official": 2799, "second_hand_avg": 2012},
    "Action_4": {"official": 1398},
    "Insta360_X4": {"official": 2999},
    "Insta360_X5": {"official": 2798},
    "DJI_Mini_3": {"official": 1699},
}

# 权重配置
weights = {
    "data_source": 0.25,
    "sample_size": 0.20,
    "consistency": 0.20,
    "trend": 0.20,
    "cross_validation": 0.15
}

def calc_data_source_score(sources):
    """数据源评分"""
    if sources >= 3:
        return 95
    elif sources == 2:
        return 75
    else:
        return 50

def calc_sample_size_score(data_points):
    """样本量评分"""
    if data_points >= 5:
        return 100
    elif data_points >= 3:
        return 80
    else:
        return 60

def calc_consistency_score(result, baseline_key):
    """一致性评分"""
    if baseline_key not in baselines:
        return 70  # 无baseline给中等分
    bl = baselines[baseline_key]
    if "avg" in bl:
        baseline_avg = bl["avg"]
        current_avg = result["current_avg"]
        deviation = abs(current_avg - baseline_avg) / baseline_avg * 100
        if deviation <= 5:
            return 100
        elif deviation <= 10:
            return 85
        elif deviation <= 20:
            return 70
        else:
            return 50
    return 80

def calc_trend_score(result, baseline_key):
    """趋势评分"""
    if baseline_key not in baselines:
        return 75
    bl = baselines[baseline_key]
    if "trend" in bl:
        if "下跌" in bl["trend"]:
            return 90  # 下跌趋势符合预期
    return 80

def calc_cross_validation_score(result, baseline_key):
    """交叉验证评分"""
    if baseline_key not in baselines:
        return 70
    bl = baselines[baseline_key]
    if "avg" in bl:
        in_range = bl["min"] <= result["current_avg"] <= bl["max"]
        return 95 if in_range else 60
    return 75

def calculate_confidence(model_key, result):
    """计算5维度置信度"""
    scores = {
        "data_source": calc_data_source_score(result["sources"]),
        "sample_size": calc_sample_size_score(result["data_points"]),
        "consistency": calc_consistency_score(result, model_key),
        "trend": calc_trend_score(result, model_key),
        "cross_validation": calc_cross_validation_score(result, model_key)
    }
    
    confidence = sum(scores[k] * weights[k] for k in weights)
    
    return {
        "total": round(confidence, 1),
        "dimensions": scores
    }

def detect_anomaly(model_key, result):
    """异动检测（5算法融合）"""
    if model_key not in baselines:
        return {"votes": 0, "level": "INFO", "algos": {}}
    
    bl = baselines[model_key]
    if "avg" not in bl:
        return {"votes": 0, "level": "INFO", "algos": {}}
    
    baseline_avg = bl["avg"]
    current_avg = result["current_avg"]
    deviation = (current_avg - baseline_avg) / baseline_avg * 100
    
    algos = {}
    votes = 0
    
    # 1. 3σ法则
    sigma = bl.get("sigma", baseline_avg * 0.1)
    if abs(current_avg - baseline_avg) > 2 * sigma:
        algos["three_sigma"] = 1
        votes += 1
    else:
        algos["three_sigma"] = 0
    
    # 2. 趋势突变 (偏离>10%)
    if abs(deviation) > 10:
        algos["trend_break"] = 1
        votes += 1
    else:
        algos["trend_break"] = 0
    
    # 3. 分布漂移 (超出区间)
    if current_avg < bl["min"] or current_avg > bl["max"]:
        algos["distribution_shift"] = 1
        votes += 1
    else:
        algos["distribution_shift"] = 0
    
    # 4. 孤立森林简化版
    if abs(deviation) > 15:
        algos["isolation_forest"] = 1
        votes += 1
    else:
        algos["isolation_forest"] = 0
    
    # 5. IQR
    q1 = bl["min"]
    q3 = bl["max"]
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    if current_avg < lower or current_avg > upper:
        algos["iqr"] = 1
        votes += 1
    else:
        algos["iqr"] = 0
    
    # 告警级别
    if votes >= 4:
        level = "CRITICAL"
    elif votes >= 3:
        level = "ALERT"
    elif votes >= 2:
        level = "WARN"
    else:
        level = "INFO"
    
    return {"votes": votes, "level": level, "algos": algos, "deviation_pct": round(deviation, 2)}

def main():
    results = []
    alerts = []
    
    for model_key, result in search_results.items():
        confidence = calculate_confidence(model_key, result)
        anomaly = detect_anomaly(model_key, result)
        
        # 决策
        if confidence["total"] >= 90:
            decision = "直接记录"
        elif confidence["total"] >= 70:
            decision = "告警队列"
        else:
            decision = "继续观察"
        
        item = {
            "model": model_key,
            "confidence": confidence["total"],
            "confidence_dims": confidence["dimensions"],
            "anomaly": anomaly,
            "decision": decision,
            "current_price": f"¥{result['current_min']}-{result['current_max']}",
            "baseline_price": baselines.get(model_key, {}).get("avg", "N/A")
        }
        results.append(item)
        
        if anomaly["level"] in ["ALERT", "CRITICAL"] or decision == "告警队列":
            alerts.append(item)
    
    # 输出结果
    output = {
        "scan_time": datetime.now().isoformat(),
        "total_models": len(results),
        "results": results,
        "alerts": alerts,
        "summary": {
            "direct_record": len([r for r in results if r["decision"] == "直接记录"]),
            "alert_queue": len([r for r in results if r["decision"] == "告警队列"]),
            "continue_observe": len([r for r in results if r["decision"] == "继续观察"]),
            "critical": len([r for r in alerts if r["anomaly"]["level"] == "CRITICAL"]),
            "alert": len([r for r in alerts if r["anomaly"]["level"] == "ALERT"]),
        }
    }
    
    return output

if __name__ == "__main__":
    import sys
    output = main()
    print(json.dumps(output, ensure_ascii=False, indent=2))
