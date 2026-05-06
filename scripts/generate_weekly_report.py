#!/usr/bin/env python3
"""
周报生成模块 v1.0

功能：
- 本周价格趋势汇总（7天走势，涨跌幅）
- 本周关键动作回顾（已执行的action）
- 下周预判与建议
  - 即将到期的信号窗口
  - 即将发布的新品
  - 即将生效的政策
  - 建议的估价调整方向
"""
import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DAILY_PRICE_DIR = DATA_DIR / "daily_price_records"
ACTION_ARCHIVE_FILE = DATA_DIR / "action_archive.json"
NEWS_SIGNALS_FILE = DATA_DIR / "news_signals_filtered.json"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
WEEKLY_REPORT_FILE = DATA_DIR / "weekly_report_payload.json"


def load_json(path):
    """加载JSON文件"""
    if not Path(path).exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path, data):
    """保存JSON文件"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(path).with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def now_iso():
    return datetime.now().isoformat()


def get_week_dates(weeks_ago=0) -> tuple:
    """获取本周的日期范围（周一到周日）"""
    today = datetime.now()
    # 找到本周一
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday) - timedelta(weeks=weeks_ago)
    sunday = monday + timedelta(days=6)
    return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d"), monday, sunday


def parse_daily_price_files() -> Dict[str, List[Dict]]:
    """解析每日价格记录文件"""
    daily_data = {}
    
    if not DAILY_PRICE_DIR.exists():
        return daily_data
    
    # 获取本周的文件
    week_start, week_end, _, _ = get_week_dates()
    
    for f in sorted(DAILY_PRICE_DIR.glob("*.json")):
        date_str = f.stem  # 文件名格式：YYYY-MM-DD
        if date_str >= week_start and date_str <= week_end:
            try:
                data = load_json(f)
                daily_data[date_str] = data
            except Exception:
                continue
    
    return daily_data


@dataclass
class ProductTrend:
    """产品趋势数据"""
    product_id: str
    product_name: str
    start_price: Optional[float] = None
    end_price: Optional[float] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    weekly_change_pct: Optional[float] = None
    daily_changes: List[Dict] = None
    trend_direction: str = "stable"  # up, down, stable
    
    def __post_init__(self):
        if self.daily_changes is None:
            self.daily_changes = []
    
    def to_dict(self) -> Dict:
        return asdict(self)


class WeeklyPriceAnalyzer:
    """本周价格趋势分析"""
    
    def __init__(self):
        self.daily_data = parse_daily_price_files()
        self.products = defaultdict(dict)
    
    def extract_product_prices(self, data: Dict, date: str) -> Dict[str, float]:
        """从数据中提取产品价格"""
        prices = {}
        
        # 尝试多种数据结构
        for key in ["prices", "models", "products"]:
            if key in data and isinstance(data[key], dict):
                for pid, pdata in data[key].items():
                    if isinstance(pdata, dict):
                        price = (
                            pdata.get("xianyu_market_price")
                            or pdata.get("price")
                            or pdata.get("median")
                            or pdata.get("avg")
                        )
                        if price and isinstance(price, (int, float)):
                            prices[pid] = price
        
        return prices
    
    def analyze(self) -> List[ProductTrend]:
        """分析本周价格趋势"""
        trends = {}
        
        # 按日期排序处理
        for date_str in sorted(self.daily_data.keys()):
            data = self.daily_data[date_str]
            prices = self.extract_product_prices(data, date_str)
            
            for pid, price in prices.items():
                if pid not in trends:
                    trends[pid] = ProductTrend(
                        product_id=pid,
                        product_name=pid,
                        daily_changes=[]
                    )
                
                trend = trends[pid]
                trend.daily_changes.append({"date": date_str, "price": price})
                
                # 更新价格范围
                if trend.min_price is None or price < trend.min_price:
                    trend.min_price = price
                if trend.max_price is None or price > trend.max_price:
                    trend.max_price = price
                
                # 记录起始和结束价格
                if trend.start_price is None:
                    trend.start_price = price
                trend.end_price = price
        
        # 计算周涨跌幅和趋势
        for trend in trends.values():
            if trend.start_price and trend.end_price and trend.start_price > 0:
                trend.weekly_change_pct = (
                    (trend.end_price - trend.start_price) / trend.start_price * 100
                )
                
                if trend.weekly_change_pct > 1:
                    trend.trend_direction = "up"
                elif trend.weekly_change_pct < -1:
                    trend.trend_direction = "down"
                else:
                    trend.trend_direction = "stable"
                
                # 更新产品名称
                if trend.daily_changes:
                    first_entry = trend.daily_changes[0]
                    data = self.daily_data.get(first_entry["date"], {})
                    for key in ["prices", "models", "products"]:
                        if key in data and isinstance(data[key], dict):
                            pdata = data[key].get(trend.product_id)
                            if pdata:
                                trend.product_name = (
                                    pdata.get("product_name")
                                    or pdata.get("name")
                                    or trend.product_id
                                )
                                break
        
        # 排序并返回
        return sorted(
            trends.values(),
            key=lambda x: abs(x.weekly_change_pct or 0),
            reverse=True
        )
    
    def generate_summary(self) -> Dict[str, Any]:
        """生成趋势汇总"""
        trends = self.analyze()
        
        if not trends:
            return {
                "analyzed_products": 0,
                "rising_count": 0,
                "falling_count": 0,
                "stable_count": 0,
                "top_rising": [],
                "top_falling": [],
            }
        
        rising = [t for t in trends if t.trend_direction == "up"]
        falling = [t for t in trends if t.trend_direction == "down"]
        stable = [t for t in trends if t.trend_direction == "stable"]
        
        return {
            "analyzed_products": len(trends),
            "rising_count": len(rising),
            "falling_count": len(falling),
            "stable_count": len(stable),
            "top_rising": [
                t.to_dict() for t in rising[:5]
            ],
            "top_falling": [
                t.to_dict() for t in falling[:5]
            ],
        }


class WeeklyActionReview:
    """本周动作回顾"""
    
    def __init__(self):
        self.archive = load_json(ACTION_ARCHIVE_FILE)
    
    def get_week_actions(self) -> List[Dict]:
        """获取本周执行的动作"""
        week_start, week_end, monday, sunday = get_week_dates()
        
        actions = self.archive.get("actions", [])
        week_actions = []
        
        for action in actions:
            created_at = action.get("created_at", "")
            if created_at:
                try:
                    action_date = datetime.fromisoformat(created_at).strftime("%Y-%m-%d")
                    if week_start <= action_date <= week_end:
                        week_actions.append(action)
                except Exception:
                    continue
        
        return week_actions
    
    def generate_summary(self) -> Dict[str, Any]:
        """生成动作回顾汇总"""
        actions = self.get_week_actions()
        
        # 按方向统计
        by_direction = defaultdict(int)
        by_action_type = defaultdict(int)
        by_product = defaultdict(int)
        
        for action in actions:
            by_direction[action.get("direction", "未知")] += 1
            by_action_type[action.get("action_type", "未知")] += 1
            product = action.get("product_name") or action.get("product_id", "未知")
            by_product[product] += 1
        
        # 找出高频产品
        top_products = sorted(by_product.items(), key=lambda x: -x[1])[:10]
        
        return {
            "total_actions": len(actions),
            "by_direction": dict(by_direction),
            "by_action_type": dict(by_action_type),
            "top_products": [{"product": p, "count": c} for p, c in top_products],
            "actions": actions[:20],  # 保留最近20条
        }


class WeeklyForecast:
    """下周预判与建议"""
    
    def __init__(self):
        self.news_data = load_json(NEWS_SIGNALS_FILE)
        self.price_cache = load_json(PRICE_CACHE_FILE)
    
    def _parse_date(self, value) -> Optional[datetime]:
        """解析日期"""
        if not value:
            return None
        text = str(value).strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None
    
    def _extract_upcoming_signals(self) -> List[Dict]:
        """提取即将到期的信号窗口"""
        upcoming = []
        today = datetime.now()
        next_week = today + timedelta(days=7)
        
        news_items = self.news_data.get("items", [])
        
        for item in news_items:
            # 检查是否有未来日期的事件
            event_date = item.get("event_date") or item.get("publish_date")
            if event_date:
                parsed = self._parse_date(event_date)
                if parsed and today <= parsed <= next_week:
                    upcoming.append({
                        "title": item.get("title", ""),
                        "type": "upcoming_event",
                        "date": event_date,
                        "source": item.get("source", ""),
                    })
            
            # 检查新品发布相关的信号
            title = item.get("title", "").lower()
            summary = item.get("summary", "").lower()
            keywords = ["发布", "上市", "预售", "新品"]
            
            if any(k in title or k in summary for k in keywords):
                published = self._parse_date(
                    item.get("published_at") or item.get("publish_date")
                )
                # 信号发布在最近7天内
                if published and (today - published).days <= 7:
                    upcoming.append({
                        "title": item.get("title", "")[:50],
                        "type": "new_product_signal",
                        "date": item.get("publish_date", ""),
                        "source": item.get("source", ""),
                    })
        
        return upcoming[:10]
    
    def _generate_policy_signals(self) -> List[Dict]:
        """生成政策相关信号"""
        policies = []
        today = datetime.now()
        
        news_items = self.news_data.get("items", [])
        
        for item in news_items[:30]:
            title = item.get("title", "")
            summary = item.get("summary", "")
            text = f"{title} {summary}".lower()
            
            policy_keywords = ["以旧换新", "补贴", "政策", "税", "回收"]
            
            if any(k in text for k in policy_keywords):
                published = self._parse_date(
                    item.get("published_at") or item.get("publish_date")
                )
                if published and (today - published).days <= 7:
                    policies.append({
                        "title": title[:60],
                        "type": "policy",
                        "action_suggestion": "配合政策制定召回活动",
                        "date": item.get("publish_date", ""),
                    })
        
        return policies[:5]
    
    def _generate_price_recommendations(self) -> List[Dict]:
        """生成估价调整建议"""
        recommendations = []
        
        # 从价格缓存中获取产品信息
        prices = self.price_cache.get("prices") or self.price_cache.get("models") or {}
        
        for pid, pdata in list(prices.items())[:20]:
            product_name = pdata.get("product_name") or pdata.get("name") or pid
            
            # 检查是否有周趋势变化
            weekly_change = pdata.get("change_7d") or pdata.get("weekly_change")
            
            if weekly_change and isinstance(weekly_change, (int, float)):
                if weekly_change > 3:  # 周涨幅超过3%
                    recommendations.append({
                        "product_id": pid,
                        "product_name": product_name,
                        "change_pct": weekly_change,
                        "recommendation": "建议上调报价抢量",
                        "recall_suggestion": "配合召回提升回收量",
                    })
                elif weekly_change < -3:  # 周跌幅超过3%
                    recommendations.append({
                        "product_id": pid,
                        "product_name": product_name,
                        "change_pct": weekly_change,
                        "recommendation": "建议下调报价控制风险",
                        "recall_suggestion": "减少召回投放",
                    })
        
        return recommendations[:10]
    
    def generate_summary(self) -> Dict[str, Any]:
        """生成预判汇总"""
        return {
            "upcoming_signals": self._extract_upcoming_signals(),
            "policy_signals": self._generate_policy_signals(),
            "price_recommendations": self._generate_price_recommendations(),
        }


class WeeklyReportGenerator:
    """周报生成器"""
    
    def __init__(self):
        self.price_analyzer = WeeklyPriceAnalyzer()
        self.action_reviewer = WeeklyActionReview()
        self.forecaster = WeeklyForecast()
    
    def generate(self) -> Dict[str, Any]:
        """生成完整周报"""
        week_start, week_end, _, _ = get_week_dates()
        
        return {
            "version": "1.0.0",
            "week_start": week_start,
            "week_end": week_end,
            "generated_at": now_iso(),
            "price_trend_summary": self.price_analyzer.generate_summary(),
            "action_review": self.action_reviewer.generate_summary(),
            "forecast": self.forecaster.generate_summary(),
        }
    
    def build_markdown(self, report: Dict) -> str:
        """构建Markdown格式周报"""
        lines = [
            f"# 📊 本周行情周报",
            f"**周期**：{report['week_start']} 至 {report['week_end']}",
            "",
        ]
        
        # 价格趋势汇总
        trend = report.get("price_trend_summary", {})
        lines.append("## 📈 本周价格趋势汇总")
        lines.append(f"- 监控产品数：{trend.get('analyzed_products', 0)}")
        lines.append(f"- 上涨产品：{trend.get('rising_count', 0)} 个")
        lines.append(f"- 下跌产品：{trend.get('falling_count', 0)} 个")
        lines.append(f"- 持平产品：{trend.get('stable_count', 0)} 个")
        lines.append("")
        
        if trend.get("top_rising"):
            lines.append("**涨幅TOP5**：")
            for item in trend["top_rising"][:5]:
                change = item.get("weekly_change_pct", 0)
                name = item.get("product_name", item.get("product_id", ""))
                lines.append(f"- {name}：+{change:.1f}%" if change >= 0 else f"- {name}：{change:.1f}%")
            lines.append("")
        
        if trend.get("top_falling"):
            lines.append("**跌幅TOP5**：")
            for item in trend["top_falling"][:5]:
                change = item.get("weekly_change_pct", 0)
                name = item.get("product_name", item.get("product_id", ""))
                lines.append(f"- {name}：{change:.1f}%")
            lines.append("")
        
        # 动作回顾
        action = report.get("action_review", {})
        lines.append("## 🚨 本周关键动作回顾")
        lines.append(f"- 执行动作总数：{action.get('total_actions', 0)}")
        
        by_direction = action.get("by_direction", {})
        if by_direction:
            parts = []
            for direction, count in by_direction.items():
                parts.append(f"{direction}{count}条")
            lines.append(f"- 动作分布：{' | '.join(parts)}")
        lines.append("")
        
        if action.get("top_products"):
            lines.append("**高频关注产品**：")
            for item in action["top_products"][:5]:
                lines.append(f"- {item['product']}：{item['count']}条动作")
            lines.append("")
        
        # 下周预判
        forecast = report.get("forecast", {})
        lines.append("## 🔮 下周预判与建议")
        
        # 即将到期的信号
        upcoming = forecast.get("upcoming_signals", [])
        if upcoming:
            lines.append("**即将到期的信号窗口**：")
            for item in upcoming[:5]:
                date = item.get("date", "")
                title = item.get("title", "")[:40]
                lines.append(f"- [{date}] {title}")
            lines.append("")
        
        # 政策信号
        policies = forecast.get("policy_signals", [])
        if policies:
            lines.append("**政策相关信号**：")
            for item in policies[:3]:
                title = item.get("title", "")[:50]
                lines.append(f"- 📋 {title}")
                lines.append(f"  → 建议：{item.get('action_suggestion', '')}")
            lines.append("")
        
        # 估价调整建议
        recommendations = forecast.get("price_recommendations", [])
        if recommendations:
            lines.append("**估价调整建议**：")
            up_recs = [r for r in recommendations if r.get("change_pct", 0) > 0]
            down_recs = [r for r in recommendations if r.get("change_pct", 0) < 0]
            
            if up_recs:
                lines.append("**建议上调**：")
                for r in up_recs[:3]:
                    lines.append(f"- {r['product_name']}（+{r['change_pct']:.1f}%）→ {r['recommendation']}")
            
            if down_recs:
                lines.append("**建议下调**：")
                for r in down_recs[:3]:
                    lines.append(f"- {r['product_name']}（{r['change_pct']:.1f}%）→ {r['recommendation']}")
            lines.append("")
        
        lines.append("---")
        lines.append(f"*报告生成时间：{report.get('generated_at', '')}*")
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="生成周报")
    parser.add_argument("--output", default=str(WEEKLY_REPORT_FILE))
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()
    
    generator = WeeklyReportGenerator()
    report = generator.generate()
    
    # 保存JSON格式
    output_json = Path(args.output)
    save_json(output_json, report)
    
    # 如果需要Markdown格式，额外输出
    if args.format == "markdown":
        markdown = generator.build_markdown(report)
        md_file = output_json.with_suffix(".md")
        md_file.write_text(markdown, encoding="utf-8")
        print(f"Markdown已保存到: {md_file}")
    
    print(f"周报已保存到: {output_json}")
    print(f"\n{'='*50}")
    print(generator.build_markdown(report))


if __name__ == "__main__":
    main()
