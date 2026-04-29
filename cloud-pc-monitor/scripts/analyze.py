#!/usr/bin/env python3
"""
趋势分析模块 - 云电脑价格追踪系统
功能：价格趋势计算、异常点识别、异动算法融合（5种算法投票）
"""

import json
import csv
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import statistics


class TrendAnalyzer:
    """趋势分析器"""
    
    def __init__(self, base_path: str = "."):
        self.base_path = Path(base_path).resolve()
        self.data_dir = self.base_path / "data"
        self.history_dir = self.data_dir / "price_history"
        self.baseline_file = self.data_dir / "baseline.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        
        # 5种异动检测算法
        self.algorithms = {
            "zscore": self._detect_zscore,
            "iqr": self._detect_iqr,
            "moving_avg": self._detect_moving_avg,
            "percentile": self._detect_percentile,
            "gradient": self._detect_gradient
        }
        
        # 默认阈值（可被threshold.py动态调整）
        self.thresholds = {
            "zscore": 2.0,
            "iqr_factor": 1.5,
            "pct_change": 0.15,
            "gradient": 0.1,
            "percentile_low": 5,
            "percentile_high": 95
        }
    
    def load_config(self) -> Dict:
        """加载阈值配置（如果存在）"""
        config_file = self.data_dir / "threshold_config.json"
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f).get("thresholds", self.thresholds)
        return self.thresholds
    
    def load_baseline(self) -> Dict:
        """加载基准数据"""
        if self.baseline_file.exists():
            with open(self.baseline_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        fallback = self.base_path.parent / "config" / "baseline.json"
        if fallback.exists():
            with open(fallback, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def load_price_history(self, product: str) -> List[Dict]:
        """加载指定产品的价格历史"""
        history_file = self.history_dir / f"{product}.csv"
        records = []
        
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(row)
        
        return records
    
    def calculate_trend(self, prices: List[float]) -> Dict:
        """计算价格趋势（线性回归）"""
        if len(prices) < 2:
            return {"trend": "insufficient_data", "slope": 0, "change_pct": 0}
        
        n = len(prices)
        x = list(range(n))
        x_mean = statistics.mean(x)
        y_mean = statistics.mean(prices)
        
        numerator = sum((x[i] - x_mean) * (prices[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        
        slope = numerator / denominator if denominator != 0 else 0
        
        if prices[0] != 0:
            change_pct = (prices[-1] - prices[0]) / prices[0] * 100
        else:
            change_pct = 0
        
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
            "direction": direction,
            "current": prices[-1] if prices else None,
            "min": min(prices) if prices else None,
            "max": max(prices) if prices else None,
            "avg": round(statistics.mean(prices), 2) if prices else None
        }
    
    def _detect_zscore(self, prices: List[float]) -> List[int]:
        """算法1: Z-score检测异常点"""
        if len(prices) < 3:
            return []
        mean = statistics.mean(prices)
        stdev = statistics.stdev(prices) if len(prices) > 1 else 0
        if stdev == 0:
            return []
        anomaly_indices = []
        for i, price in enumerate(prices):
            if abs((price - mean) / stdev) > self.thresholds["zscore"]:
                anomaly_indices.append(i)
        return anomaly_indices
    
    def _detect_iqr(self, prices: List[float]) -> List[int]:
        """算法2: IQR检测异常点"""
        if len(prices) < 4:
            return []
        sorted_prices = sorted(prices)
        n = len(sorted_prices)
        q1 = sorted_prices[n // 4]
        q3 = sorted_prices[3 * n // 4]
        iqr = q3 - q1
        lower = q1 - self.thresholds["iqr_factor"] * iqr
        upper = q3 + self.thresholds["iqr_factor"] * iqr
        return [i for i, p in enumerate(prices) if p < lower or p > upper]
    
    def _detect_moving_avg(self, prices: List[float], window: int = 3) -> List[int]:
        """算法3: 移动平均检测"""
        if len(prices) < window + 1:
            return []
        anomaly_indices = []
        for i in range(window, len(prices)):
            avg = statistics.mean(prices[i-window:i])
            if avg != 0 and abs(prices[i] - avg) / avg > self.thresholds["pct_change"]:
                anomaly_indices.append(i)
        return anomaly_indices
    
    def _detect_percentile(self, prices: List[float]) -> List[int]:
        """算法4: 百分位法检测"""
        if len(prices) < 5:
            return []
        sorted_prices = sorted(prices)
        n = len(sorted_prices)
        p5 = sorted_prices[int(n * 0.05)]
        p95 = sorted_prices[int(n * 0.95)]
        return [i for i, p in enumerate(prices) if p < p5 or p > p95]
    
    def _detect_gradient(self, prices: List[float]) -> List[int]:
        """算法5: 梯度检测"""
        if len(prices) < 3:
            return []
        anomaly_indices = []
        for i in range(1, len(prices)):
            if prices[i-1] != 0:
                gradient = abs((prices[i] - prices[i-1]) / prices[i-1])
                if gradient > self.thresholds["gradient"]:
                    anomaly_indices.append(i)
        return anomaly_indices
    
    def vote_anomaly(self, prices: List[float], dates: List[str] = None) -> Dict:
        """5种算法投票融合"""
        votes = defaultdict(list)
        for algo_name, algo_func in self.algorithms.items():
            for idx in algo_func(prices):
                date = dates[idx] if dates and idx < len(dates) else str(idx)
                votes[date].append(algo_name)
        
        anomalies = []
        for date, algo_list in votes.items():
            if len(algo_list) >= 3:  # 超过半数票
                anomalies.append({
                    "date": date,
                    "vote_count": len(algo_list),
                    "algorithms": algo_list,
                    "confidence": len(algo_list) / len(self.algorithms)
                })
        
        return {
            "anomalies": anomalies,
            "algo_count": len(self.algorithms),
            "voted_algos": list(set(algo for v in votes.values() for algo in v))
        }
    
    def analyze_product(self, product: str) -> Dict:
        """分析单个产品"""
        history = self.load_price_history(product)
        prices = []
        dates = []
        
        for record in history:
            if "price" in record:
                try:
                    prices.append(float(record["price"]))
                    dates.append(record.get("date", record.get("timestamp", "")))
                except (ValueError, KeyError):
                    continue
        
        if not prices:
            return {"product": product, "status": "no_data"}
        
        # 应用阈值配置
        self.thresholds = self.load_config()
        
        trend = self.calculate_trend(prices[-7:] if len(prices) >= 7 else prices)
        anomaly_result = self.vote_anomaly(prices, dates)
        
        return {
            "product": product,
            "status": "success",
            "trend": trend,
            "anomaly_detection": anomaly_result,
            "sample_count": len(prices),
            "last_updated": dates[-1] if dates else None
        }
    
    def analyze_all(self) -> Dict:
        """分析所有产品"""
        baseline = self.load_baseline()
        results = {
            "analyzed_at": datetime.now().isoformat(),
            "products": {},
            "summary": {"total": 0, "rising": 0, "falling": 0, "stable": 0, "anomalies": 0}
        }
        
        if baseline and "baselines" in baseline:
            for product in baseline["baselines"].keys():
                result = self.analyze_product(product)
                results["products"][product] = result
                
                if result["status"] == "success":
                    results["summary"]["total"] += 1
                    trend = result.get("trend", {}).get("trend", "unknown")
                    results["summary"][trend] = results["summary"].get(trend, 0) + 1
                    
                    if result.get("anomaly_detection", {}).get("anomalies"):
                        results["summary"]["anomalies"] += 1
        
        return results
    
    def save_analysis_result(self, results: Dict) -> str:
        """保存分析结果"""
        output_file = self.data_dir / "trend_analysis.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[保存] 趋势分析结果: {output_file}")
        return str(output_file)


def main():
    """主函数"""
    print("=" * 50)
    print("云电脑价格趋势分析")
    print("=" * 50)
    
    analyzer = TrendAnalyzer(base_path=".")
    results = analyzer.analyze_all()
    
    print(f"\n[分析摘要]")
    print(f"分析时间: {results['analyzed_at']}")
    print(f"总产品数: {results['summary']['total']}")
    print(f"涨价: {results['summary']['rising']} | 下跌: {results['summary']['falling']} | 稳定: {results['summary']['stable']}")
    print(f"异常检测: {results['summary']['anomalies']}个")
    
    analyzer.save_analysis_result(results)
    return results


if __name__ == "__main__":
    main()
