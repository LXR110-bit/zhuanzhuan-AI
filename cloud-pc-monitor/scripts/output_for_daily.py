#!/usr/bin/env python3
"""
日报数据输出模块 - 云电脑价格追踪系统
功能：将云电脑扫描数据输出为日报可读取的JSON格式
整合到现有市场追踪日报体系中
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# 添加scripts目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from analyze import TrendAnalyzer


class DailyReportOutput:
    """日报数据输出器"""
    
    def __init__(self, base_path: str = None):
        if base_path is None:
            # 默认：向上两级到运动相机追踪目录
            self.base_path = Path(__file__).parent.parent.parent
        else:
            self.base_path = Path(base_path).resolve()
        
        # 云电脑监控目录
        self.monitor_dir = self.base_path / "cloud-pc-monitor"
        self.data_dir = self.monitor_dir / "data"
        self.analyzer = TrendAnalyzer(base_path=self.monitor_dir)
        
        # 输出路径：与市场追踪日报同目录
        self.output_dir = self.base_path
        
        # 品类映射
        self.category_map = {
            "RTX_3070": ("显卡", "GPU"),
            "RTX_3090": ("显卡", "GPU"),
            "RTX_4060": ("显卡", "GPU"),
            "RTX_4070": ("显卡", "GPU"),
            "RTX_4080": ("显卡", "GPU"),
            "RX_6600": ("显卡", "GPU"),
            "RX_7600": ("显卡", "GPU"),
            "i5_13600K": ("CPU", "CPU"),
            "i7_13700K": ("CPU", "CPU"),
            "DDR5_16G": ("内存", "存储"),
            "DDR5_32G": ("内存", "存储"),
            "Pocket_3": ("运动相机", "运动相机"),
            "Pocket_2": ("运动相机", "运动相机"),
            "Action_4": ("运动相机", "运动相机"),
            "Action_5": ("运动相机", "运动相机"),
            "Insta360_X4": ("全景相机", "全景相机"),
            "Insta360_X5": ("全景相机", "全景相机"),
            "DJI_Mini_3": ("无人机", "无人机"),
            "DJI_Mini_4": ("无人机", "无人机"),
            "GoPro_11": ("运动相机", "运动相机"),
            "GoPro_12": ("运动相机", "运动相机"),
        }
    
    def load_baseline(self) -> dict:
        """加载基准数据"""
        baseline_file = self.data_dir / "baseline.json"
        if baseline_file.exists():
            with open(baseline_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        fallback = self.base_path / "config" / "baseline.json"
        if fallback.exists():
            with open(fallback, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def load_trend_analysis(self) -> dict:
        """加载趋势分析结果"""
        analysis_file = self.data_dir / "trend_analysis.json"
        if analysis_file.exists():
            with open(analysis_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def load_alerts(self) -> list:
        """加载告警队列"""
        alert_file = self.data_dir / "alert_queue.json"
        if alert_file.exists():
            with open(alert_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        return []
    
    def categorize_product(self, product: str) -> tuple:
        """获取产品品类"""
        # 精确匹配
        if product in self.category_map:
            return self.category_map[product]
        
        # 模糊匹配
        product_lower = product.lower()
        if "rtx" in product_lower or "rx" in product_lower or "gpu" in product_lower:
            return ("显卡", "GPU")
        if "i5" in product_lower or "i7" in product_lower or "cpu" in product_lower:
            return ("CPU", "CPU")
        if "ddr" in product_lower:
            return ("内存", "存储")
        if "pocket" in product_lower:
            return ("运动相机", "运动相机")
        if "action" in product_lower or "gopro" in product_lower:
            return ("运动相机", "运动相机")
        if "insta360" in product_lower:
            return ("全景相机", "全景相机")
        if "mini" in product_lower or "dji" in product_lower:
            return ("无人机", "无人机")
        
        return ("其他", "其他")
    
    def build_price_table(self, baseline: dict, trends: dict) -> list:
        """构建价格数据表格（日报格式）"""
        table = []
        
        if not baseline or "baselines" not in baseline:
            return table
        
        for product, data in baseline["baselines"].items():
            cat, _ = self.categorize_product(product)
            trend_data = trends.get("products", {}).get(product, {})
            trend = trend_data.get("trend", {})
            
            # 格式化产品名（RTX_3070 -> RTX 3070）
            display_name = product.replace("_", " ")
            
            # 构建行数据
            row = {
                "品类": cat,
                "机型": display_name,
                "当前价格": self._format_price(data),
                "价格区间": self._format_range(data),
                "趋势": self._get_trend_emoji(trend.get("trend", "unknown")),
                "变化": f"{trend.get('change_pct', 0):+.1f}%" if trend.get("change_pct") else "-",
                "备注": data.get("trend", data.get("source", ""))
            }
            table.append(row)
        
        return table
    
    def _format_price(self, data: dict) -> str:
        """格式化价格"""
        if "official" in data:
            return f"¥{data['official']}"
        if "avg" in data:
            return f"¥{data['avg']}"
        if "avg_eur" in data:
            return f"€{data['avg_eur']}"
        return "-"
    
    def _format_range(self, data: dict) -> str:
        """格式化价格区间"""
        if "min" in data and "max" in data:
            return f"¥{data['min']}-{data['max']}"
        if "min_eur" in data and "max_eur" in data:
            return f"€{data['min_eur']}-{data['max_eur']}"
        if "second_hand_min" in data and "second_hand_max" in data:
            return f"¥{data['second_hand_min']}-{data['second_hand_max']}二手"
        return "-"
    
    def _get_trend_emoji(self, trend: str) -> str:
        """趋势表情"""
        emoji_map = {
            "rising": "↑",
            "falling": "↓",
            "stable": "→",
            "unknown": "-"
        }
        return emoji_map.get(trend, "-")
    
    def build_signals(self, trends: dict, alerts: list) -> dict:
        """构建信号数据（日报格式）"""
        signals = {
            "S级": [],
            "A级": [],
            "B级": []
        }
        
        # 从趋势分析中提取异动
        if trends and "products" in trends:
            for product, result in trends["products"].items():
                if result.get("status") != "success":
                    continue
                
                trend = result.get("trend", {})
                anomalies = result.get("anomaly_detection", {}).get("anomalies", [])
                
                display_name = product.replace("_", " ")
                
                # 根据变化幅度定级
                change_pct = abs(trend.get("change_pct", 0))
                
                if anomalies or change_pct >= 15:
                    signal = {
                        "产品": display_name,
                        "变化": f"{trend.get('change_pct', 0):+.1f}%",
                        "趋势": trend.get("trend", "unknown"),
                        "置信度": f"{len(anomalies) * 20}%" if anomalies else "-"
                    }
                    
                    if change_pct >= 20:
                        signals["S级"].append(signal)
                    elif change_pct >= 10:
                        signals["A级"].append(signal)
                    else:
                        signals["B级"].append(signal)
        
        # 从告警队列添加
        for alert in alerts[:5]:
            if alert.get("severity") == "high":
                signals["A级"].append({
                    "产品": alert.get("product", "未知"),
                    "变化": "告警",
                    "趋势": "异动",
                    "置信度": f"{alert.get('confidence', 0) * 100:.0f}%"
                })
        
        return signals
    
    def build_recommendations(self, trends: dict) -> list:
        """构建运营建议"""
        recommendations = []
        
        summary = trends.get("summary", {})
        
        # 分类汇总
        by_category = defaultdict(lambda: {"rising": 0, "falling": 0})
        
        if trends and "products" in trends:
            for product, result in trends["products"].items():
                if result.get("status") != "success":
                    continue
                
                cat, _ = self.categorize_product(product)
                trend = result.get("trend", {}).get("trend", "stable")
                
                if trend in by_category[cat]:
                    by_category[cat][trend] += 1
        
        # 生成建议
        for cat, stats in by_category.items():
            if stats["falling"] > stats["rising"]:
                recommendations.append(f"{cat}持续下跌，关注用户'卖旧换新'需求")
            elif stats["rising"] > stats["falling"]:
                recommendations.append(f"{cat}价格上涨，回收定价需跟进调整")
        
        if summary.get("anomalies", 0) > 0:
            recommendations.append(f"检测到{summary['anomalies']}个价格异常，建议核实")
        
        if not recommendations:
            recommendations.append("市场整体平稳，无特殊建议")
        
        return recommendations
    
    def generate_daily_data(self) -> dict:
        """生成日报数据"""
        baseline = self.load_baseline()
        trends = self.load_trend_analysis()
        alerts = self.load_alerts()
        
        # 先运行趋势分析
        if not trends:
            print("[分析] 运行趋势分析...")
            trends = self.analyzer.analyze_all()
            self.analyzer.save_analysis_result(trends)
        
        # 如果没有运行过分析，强制分析一次
        if not trends.get("products"):
            trends = self.analyzer.analyze_all()
            self.analyzer.save_analysis_result(trends)
        
        report_data = {
            "source": "云电脑价格扫描",
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_products": len(baseline.get("baselines", {})),
                "trends": trends.get("summary", {}),
                "pending_alerts": len(alerts)
            },
            "price_table": self.build_price_table(baseline, trends),
            "signals": self.build_signals(trends, alerts),
            "recommendations": self.build_recommendations(trends)
        }
        
        return report_data
    
    def save_for_daily_report(self, data: dict) -> str:
        """保存供日报读取的数据文件"""
        # 输出到行情追踪助手目录
        output_file = self.output_dir / "cloud_pc_daily.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[输出] 日报数据已保存: {output_file}")
        return str(output_file)
    
    def print_summary(self, data: dict):
        """打印摘要（用于日志）"""
        print("=" * 50)
        print("云电脑价格扫描 - 日报数据输出")
        print("=" * 50)
        
        summary = data.get("summary", {})
        trends = summary.get("trends", {})
        
        print(f"\n📊 监控概况")
        print(f"   产品总数: {summary.get('total_products', 0)}")
        print(f"   涨价趋势: {trends.get('rising', 0)} | 下跌趋势: {trends.get('falling', 0)} | 稳定: {trends.get('stable', 0)}")
        print(f"   异常检测: {trends.get('anomalies', 0)}")
        print(f"   待处理告警: {summary.get('pending_alerts', 0)}")
        
        # 价格表格预览
        table = data.get("price_table", [])
        if table:
            print(f"\n📋 价格数据 ({len(table)}条)")
            print("-" * 60)
            for row in table[:8]:
                print(f"   {row['品类']:6} {row['机型']:12} {row['当前价格']:10} {row['趋势']} {row['变化']:>6}")
            if len(table) > 8:
                print(f"   ... 还有{len(table) - 8}条")
        
        # 信号预览
        signals = data.get("signals", {})
        for level in ["S级", "A级"]:
            items = signals.get(level, [])
            if items:
                print(f"\n{level}信号 ({len(items)}个)")
                for item in items[:3]:
                    print(f"   • {item['产品']}: {item['变化']}")
        
        # 建议预览
        recs = data.get("recommendations", [])
        if recs:
            print(f"\n💡 运营建议")
            for rec in recs[:3]:
                print(f"   • {rec}")
        
        print(f"\n⏰ 生成时间: {data.get('generated_at', '-')}")


def main():
    """主函数"""
    print("=" * 50)
    print("生成云电脑日报数据")
    print("=" * 50)
    
    # 向上两级目录：scripts -> cloud-pc-monitor -> 运动相机追踪
    base_path = Path(__file__).parent.parent.parent
    print(f"工作目录: {base_path}")
    
    output = DailyReportOutput(base_path=base_path)
    
    # 生成数据
    data = output.generate_daily_data()
    
    # 保存
    output_file = output.save_for_daily_report(data)
    
    # 打印摘要
    output.print_summary(data)
    
    return data


if __name__ == "__main__":
    main()
