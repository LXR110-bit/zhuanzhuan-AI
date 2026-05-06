#!/usr/bin/env python3
"""
信号→动作映射规则引擎 v1.0

功能：
- 信号类型分类（价格异动、上游供应链、新品发布、政策面、竞品动态）
- 每种信号对应的标准动作（估价调整、召回投放、库存出清等）
- 置信度分级逻辑（单源/双源/三源验证）
- 动作输出格式
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any


# ==================== 常量定义 ====================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
DAILY_PRICE_DIR = DATA_DIR / "daily_price_records"
ACTION_ARCHIVE_FILE = DATA_DIR / "action_archive.json"


class SignalType(Enum):
    """信号类型枚举"""
    PRICE_DROP = "price_drop"           # 行情价连续下跌
    PRICE_RISE = "price_rise"           # 行情价连续上涨
    SUPPLY_CHAIN = "supply_chain"       # 上游供应链信号
    NEW_PRODUCT = "new_product"         # 新品发布/评测爆发
    POLICY = "policy"                   # 政策面信号
    COMPETITOR = "competitor"           # 竞品动态
    ANOMALY = "anomaly"                 # 异动检测


class ActionType(Enum):
    """动作类型枚举"""
    PAUSE_HIGH_PRICE_RECYCLING = "pause_high_price_recycling"  # 暂停高价回收
    LOWER_QUOTE = "lower_quote"          # 降低报价
    RAISE_QUOTE = "raise_quote"         # 提高报价抢量
    RECALL_CAMPAIGN = "recall_campaign" # 召回投放
    STOCK_CLEARANCE = "stock_clearance" # 库存出清
    PRE_STOCK = "pre_stock"             # 预判囤货
    ACCELERATE_SHIPMENT = "accelerate_shipment"  # 加速出货
    POLICY_CAMPAIGN = "policy_campaign" # 配合政策活动
    FOLLOW_PRICE = "follow_price"       # 跟价策略
    DIFFERENTIATE = "differentiate"     # 差异化策略
    MONITOR = "monitor"                 # 持续监控
    MANUAL_CONFIRM = "manual_confirm"   # 需人工确认


class ActionDirection(Enum):
    """动作方向枚举"""
    UP = "上调"
    DOWN = "下调"
    MONITOR = "监控"
    HOLD = "维持"


class ConfidenceLevel(Enum):
    """置信度等级"""
    SINGLE_SOURCE = "单源"    # 单数据源验证
    DUAL_SOURCE = "双源"      # 双数据源验证
    TRIPLE_SOURCE = "三源"   # 三数据源验证


# ==================== 召回画像配置 ====================

RECALL_PROFILES = {
    # 安卓手机+客单价>500 → 电脑办公
    "android_high_value": {
        "source_category": "手机",
        "source_condition": "安卓",
        "min_order_amount": 500,
        "target_category": "电脑办公",
        "recall_channel": ["push", "sms"],
        "expected_roi": 10,
    },
    # 苹果手机+客单价>1500 → 电脑办公
    "iphone_high_value": {
        "source_category": "手机",
        "source_condition": "苹果",
        "min_order_amount": 1500,
        "target_category": "电脑办公",
        "recall_channel": ["push", "sms"],
        "expected_roi": 10,
    },
    # 非苹果笔记本+客单价>1500 → 电脑办公
    "non_apple_laptop": {
        "source_category": "笔记本电脑",
        "source_condition": "非苹果",
        "min_order_amount": 1500,
        "target_category": "电脑办公",
        "recall_channel": ["push", "sms"],
        "expected_roi": 10,
    },
}


# ==================== 规则配置 ====================

@dataclass
class RuleConfig:
    """规则配置"""
    signal_type: SignalType
    action_type: ActionType
    direction: ActionDirection
    trigger_conditions: Dict[str, Any]
    auto_confirm: bool = True
    confidence_base: int = 60
    cooldown_hours: int = 24
    description: str = ""


# 核心规则映射表
SIGNAL_ACTION_RULES = {
    # 行情价连续3天下跌>5% → 暂停高价回收，降低报价
    SignalType.PRICE_DROP: RuleConfig(
        signal_type=SignalType.PRICE_DROP,
        action_type=ActionType.PAUSE_HIGH_PRICE_RECYCLING,
        direction=ActionDirection.DOWN,
        trigger_conditions={
            "consecutive_days": 3,
            "drop_threshold": -0.05,  # -5%
            "platforms": ["xianyu_market", "aihuishou"],
        },
        auto_confirm=True,
        confidence_base=75,
        description="行情价连续3天下跌>5%，建议暂停高价回收，降低报价"
    ),
    
    # 行情价连续3天上涨>5% → 提高报价抢量，短信召回
    SignalType.PRICE_RISE: RuleConfig(
        signal_type=SignalType.PRICE_RISE,
        action_type=ActionType.RAISE_QUOTE,
        direction=ActionDirection.UP,
        trigger_conditions={
            "consecutive_days": 3,
            "rise_threshold": 0.05,  # +5%
            "platforms": ["xianyu_market", "aihuishou"],
        },
        auto_confirm=True,
        confidence_base=75,
        description="行情价连续3天上涨>5%，建议提高报价抢量，配合召回"
    ),
    
    # 上游涨价信号 → 预判7天后涨价，提前囤货
    SignalType.SUPPLY_CHAIN: RuleConfig(
        signal_type=SignalType.SUPPLY_CHAIN,
        action_type=ActionType.PRE_STOCK,
        direction=ActionDirection.UP,
        trigger_conditions={
            "lead_time_days": 7,
            "source_types": ["factory", "distributor", "upstream"],
        },
        auto_confirm=False,  # 需人工确认
        confidence_base=60,
        description="上游涨价信号，建议预判7天后涨价，提前囤货"
    ),
    
    # 新品发布/评测爆发 → 旧款将贬值，加速出货
    SignalType.NEW_PRODUCT: RuleConfig(
        signal_type=SignalType.NEW_PRODUCT,
        action_type=ActionType.ACCELERATE_SHIPMENT,
        direction=ActionDirection.DOWN,
        trigger_conditions={
            "signal_sources": ["tech_news", "review", "official_release"],
            "old_model_discount": 0.10,  # 旧款预估贬值10%
        },
        auto_confirm=True,
        confidence_base=80,
        description="新品发布/评测爆发，旧款将贬值，建议加速出货"
    ),
    
    # 以旧换新政策发布 → 配合政策做召回活动
    SignalType.POLICY: RuleConfig(
        signal_type=SignalType.POLICY,
        action_type=ActionType.POLICY_CAMPAIGN,
        direction=ActionDirection.MONITOR,
        trigger_conditions={
            "policy_types": ["trade_in", "subsidy", "tax_refund"],
            "requires_coordination": True,
        },
        auto_confirm=False,  # 需人工确认
        confidence_base=70,
        description="以旧换新政策发布，建议配合政策做召回活动"
    ),
    
    # 竞品提价 → 跟价或差异化策略
    SignalType.COMPETITOR: RuleConfig(
        signal_type=SignalType.COMPETITOR,
        action_type=ActionType.FOLLOW_PRICE,
        direction=ActionDirection.UP,
        trigger_conditions={
            "competitor_price_change": 0.03,  # 竞品价格变动>3%
            "market_share_impact": "high",
        },
        auto_confirm=True,
        confidence_base=65,
        description="竞品提价，建议评估跟价或差异化策略"
    ),
    
    # 异动检测 → 根据异动方向决定动作
    SignalType.ANOMALY: RuleConfig(
        signal_type=SignalType.ANOMALY,
        action_type=ActionType.MONITOR,
        direction=ActionDirection.MONITOR,
        trigger_conditions={
            "anomaly_threshold": 0.15,  # 偏离>15%
            "vote_count_min": 2,
        },
        auto_confirm=True,
        confidence_base=70,
        description="检测到价格异动，建议加强监控"
    ),
}


# ==================== 数据类定义 ====================

@dataclass
class ActionItem:
    """动作输出格式"""
    product_id: str
    product_name: str
    signal_type: str
    action_type: str
    direction: str
    change_pct: Optional[float] = None
    suggested_adjustment: Optional[str] = None
    recall_profile_match: Optional[str] = None
    confidence_level: str = "单源"
    confidence_score: int = 60
    source_signals: List[str] = field(default_factory=list)
    auto_confirm: bool = True
    description: str = ""
    created_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==================== 核心引擎类 ====================

class ActionEngine:
    """信号→动作映射引擎"""
    
    def __init__(self):
        self.rules = SIGNAL_ACTION_RULES
        self.recall_profiles = RECALL_PROFILES
        self._load_price_cache()
        self._load_action_archive()
    
    def _load_price_cache(self):
        """加载价格缓存"""
        if PRICE_CACHE_FILE.exists():
            try:
                with open(PRICE_CACHE_FILE, "r", encoding="utf-8") as f:
                    self.price_cache = json.load(f)
            except Exception:
                self.price_cache = {}
        else:
            self.price_cache = {}
    
    def _load_action_archive(self):
        """加载动作历史存档"""
        if ACTION_ARCHIVE_FILE.exists():
            try:
                with open(ACTION_ARCHIVE_FILE, "r", encoding="utf-8") as f:
                    self.action_archive = json.load(f)
            except Exception:
                self.action_archive = {"actions": []}
        else:
            self.action_archive = {"actions": []}
    
    def _save_action_archive(self):
        """保存动作历史存档"""
        ACTION_ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = ACTION_ARCHIVE_FILE.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.action_archive, f, ensure_ascii=False, indent=2)
        tmp_path.replace(ACTION_ARCHIVE_FILE)
    
    def _check_cooldown(self, product_id: str, signal_type: SignalType) -> bool:
        """检查是否在冷却期内"""
        actions = self.action_archive.get("actions", [])
        now = datetime.now()
        rule = self.rules.get(signal_type)
        if not rule:
            return False
        
        for action in reversed(actions[-10:]):  # 只检查最近10条
            if action.get("product_id") == product_id and action.get("signal_type") == signal_type.value:
                created_at = datetime.fromisoformat(action.get("created_at", "2000-01-01"))
                hours_diff = (now - created_at).total_seconds() / 3600
                if hours_diff < rule.cooldown_hours:
                    return True  # 在冷却期内
        return False
    
    def _calculate_confidence(
        self,
        signal_type: SignalType,
        source_count: int,
        consistency_score: float = 0.8
    ) -> tuple:
        """计算置信度（单源/双源/三源验证）"""
        rule = self.rules.get(signal_type)
        base_score = rule.confidence_base if rule else 60
        
        # 多源验证加成
        if source_count >= 3:
            source_bonus = 25
            level = ConfidenceLevel.TRIPLE_SOURCE
        elif source_count == 2:
            source_bonus = 15
            level = ConfidenceLevel.DUAL_SOURCE
        else:
            source_bonus = 0
            level = ConfidenceLevel.SINGLE_SOURCE
        
        # 一致性加成
        consistency_bonus = int((consistency_score - 0.5) * 40)  # 0.5-1.0 -> 0-20
        
        total_score = min(100, base_score + source_bonus + consistency_bonus)
        return total_score, level.value
    
    def _get_recall_profile_match(
        self,
        product_name: str,
        category: str,
        order_amount: Optional[float] = None
    ) -> Optional[str]:
        """检查是否匹配召回画像"""
        product_lower = product_name.lower()
        
        for profile_id, profile in self.recall_profiles.items():
            # 检查品类匹配
            if profile["source_category"] not in category:
                continue
            
            # 检查条件匹配
            condition = profile["source_condition"]
            if condition == "苹果" and ("iphone" in product_lower or "苹果" in product_lower or "apple" in product_lower):
                pass  # 匹配
            elif condition == "安卓" and not any(x in product_lower for x in ["iphone", "苹果", "apple"]):
                pass  # 匹配
            elif condition == "非苹果":
                if not any(x in product_lower for x in ["apple", "苹果", "macbook"]):
                    pass  # 匹配
            else:
                continue
            
            # 检查客单价
            if order_amount and order_amount < profile["min_order_amount"]:
                continue
            
            return profile_id
        
        return None
    
    def _get_price_trend(self, product_id: str, days: int = 7) -> tuple:
        """获取价格趋势"""
        trend = {"days": 0, "changes": [], "direction": "stable", "change_pct": 0.0}
        
        # 从每日价格记录中读取
        if not DAILY_PRICE_DIR.exists():
            return trend
        
        # 读取最近几天的价格文件
        price_files = sorted(DAILY_PRICE_DIR.glob("*.json"))
        recent_files = price_files[-days:] if len(price_files) >= days else price_files
        
        prices = []
        for f in recent_files:
            try:
                data = json.load(open(f, "r", encoding="utf-8"))
                # 尝试从数据结构中获取该产品
                for key in ["prices", "models", "products"]:
                    if key in data and isinstance(data[key], dict):
                        product_data = data[key].get(product_id)
                        if product_data:
                            price = product_data.get("xianyu_market_price") or product_data.get("price")
                            if price and isinstance(price, (int, float)):
                                prices.append({"file": f.name, "price": price})
                                break
            except Exception:
                continue
        
        if len(prices) >= 2:
            first_price = prices[0]["price"]
            last_price = prices[-1]["price"]
            change_pct = (last_price - first_price) / first_price * 100 if first_price else 0
            trend["change_pct"] = change_pct
            trend["direction"] = "up" if change_pct > 1 else "down" if change_pct < -1 else "stable"
            trend["days"] = len(prices)
            trend["changes"] = prices
        
        return trend
    
    def process_signal(self, signal_data: Dict[str, Any]) -> Optional[ActionItem]:
        """处理单个信号，生成动作建议"""
        signal_type_str = signal_data.get("type") or signal_data.get("signal_type", "")
        product_id = signal_data.get("product_id", "")
        product_name = signal_data.get("product_name", "") or signal_data.get("title", "")
        change_pct = signal_data.get("change_pct") or signal_data.get("change")
        category = signal_data.get("category", "")
        sources = signal_data.get("sources", [])
        confidence = signal_data.get("confidence", 0)
        level = signal_data.get("level", "B")
        
        # 转换信号类型
        try:
            signal_type = SignalType(signal_type_str)
        except ValueError:
            # 尝试从标题或内容推断
            if "上涨" in str(signal_data) or (isinstance(change_pct, (int, float)) and change_pct > 0):
                signal_type = SignalType.PRICE_RISE
            elif "下跌" in str(signal_data) or (isinstance(change_pct, (int, float)) and change_pct < 0):
                signal_type = SignalType.PRICE_DROP
            else:
                signal_type = SignalType.ANOMALY
        
        # 检查冷却期
        if self._check_cooldown(product_id, signal_type):
            return None
        
        # 获取对应规则
        rule = self.rules.get(signal_type)
        if not rule:
            return None
        
        # 检查触发条件
        if not self._check_trigger_conditions(signal_data, rule, change_pct):
            return None
        
        # 计算置信度
        source_count = len(sources) if sources else 1
        consistency = confidence / 100 if confidence else 0.8
        confidence_score, confidence_level = self._calculate_confidence(
            signal_type, source_count, consistency
        )
        
        # 检查召回画像匹配
        recall_match = self._get_recall_profile_match(product_name, category)
        
        # 生成动作建议
        suggested_adjustment = self._generate_adjustment_text(
            signal_type, change_pct, rule.direction
        )
        
        # 构建动作项
        action = ActionItem(
            product_id=product_id,
            product_name=product_name or product_id,
            signal_type=signal_type.value,
            action_type=rule.action_type.value,
            direction=rule.direction.value,
            change_pct=float(change_pct) if change_pct else None,
            suggested_adjustment=suggested_adjustment,
            recall_profile_match=recall_match,
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            source_signals=[str(s) for s in sources][:3],  # 最多3个来源
            auto_confirm=rule.auto_confirm,
            description=rule.description,
            created_at=datetime.now().isoformat(),
        )
        
        # 调整置信度和确认方式（根据信号级别）
        if level == "S":
            action.confidence_score = min(100, action.confidence_score + 10)
            action.description = f"【S级信号】{action.description}"
        elif level == "A":
            action.description = f"【A级信号】{action.description}"
        
        return action
    
    def _check_trigger_conditions(
        self,
        signal_data: Dict[str, Any],
        rule: RuleConfig,
        change_pct: Optional[float]
    ) -> bool:
        """检查是否满足触发条件"""
        conditions = rule.trigger_conditions
        
        # 检查价格变动阈值
        if "drop_threshold" in conditions and isinstance(change_pct, (int, float)):
            if change_pct >= conditions["drop_threshold"]:
                return True
        if "rise_threshold" in conditions and isinstance(change_pct, (int, float)):
            if change_pct >= conditions["rise_threshold"]:
                return True
        
        # 检查异动阈值
        if "anomaly_threshold" in conditions and isinstance(change_pct, (int, float)):
            if abs(change_pct) >= conditions["anomaly_threshold"]:
                return True
        
        # 检查投票数
        if "vote_count_min" in conditions:
            vote_count = signal_data.get("vote_count", 0)
            if vote_count < conditions["vote_count_min"]:
                return False
        
        # 如果没有特定阈值条件，默认通过
        return True
    
    def _generate_adjustment_text(
        self,
        signal_type: SignalType,
        change_pct: Optional[float],
        direction: ActionDirection
    ) -> str:
        """生成调整建议文本"""
        if isinstance(change_pct, (int, float)):
            pct_str = f"{change_pct:+.1f}%"
        else:
            pct_str = ""
        
        adjustments = {
            SignalType.PRICE_DROP: f"建议下调报价 {pct_str} 或暂停高价回收",
            SignalType.PRICE_RISE: f"建议上调报价 {pct_str} 抢量，配合召回",
            SignalType.SUPPLY_CHAIN: "建议预判7天后涨价，提前囤货",
            SignalType.NEW_PRODUCT: "建议加速旧款出货，降低库存",
            SignalType.POLICY: "建议配合政策制定召回活动",
            SignalType.COMPETITOR: "建议评估跟价或差异化策略",
            SignalType.ANOMALY: f"建议加强监控，变动{pct_str}",
        }
        
        return adjustments.get(signal_type, "建议持续监控")
    
    def generate_actions_from_payload(self, payload: Dict[str, Any]) -> List[ActionItem]:
        """从日报payload生成动作建议"""
        actions = []
        
        # 1. 处理S/A级异动信号
        signals = payload.get("signals", {})
        for level in ("S", "A"):
            for signal in signals.get(level, []):
                raw = signal.get("raw", signal)
                change_pct = raw.get("change_pct") or raw.get("change")
                
                # 推断信号类型
                if isinstance(change_pct, (int, float)):
                    if change_pct < -0.05:
                        signal_type = SignalType.PRICE_DROP
                    elif change_pct > 0.05:
                        signal_type = SignalType.PRICE_RISE
                    else:
                        signal_type = SignalType.ANOMALY
                else:
                    signal_type = SignalType.ANOMALY
                
                signal_data = {
                    "type": signal_type.value,
                    "product_id": raw.get("product_id", ""),
                    "product_name": raw.get("product_name", "") or signal.get("title", ""),
                    "change_pct": change_pct,
                    "level": level,
                    "sources": [signal.get("source", "unknown")],
                    "confidence": raw.get("confidence", 70),
                }
                
                action = self.process_signal(signal_data)
                if action:
                    actions.append(action)
        
        # 2. 处理新闻资讯信号
        news_data = payload.get("news_signals", {}) or payload.get("news", {})
        for item in news_data.get("items", [])[:10]:
            title = item.get("title", "")
            summary = item.get("summary", "") or item.get("description", "")
            source = item.get("source", "")
            
            # 判断信号类型
            signal_type = None
            if any(x in title.lower() or x in summary.lower() for x in ["新品", "发布", "发布"]):
                signal_type = SignalType.NEW_PRODUCT
            elif any(x in title.lower() or x in summary.lower() for x in ["政策", "补贴", "以旧换新"]):
                signal_type = SignalType.POLICY
            elif any(x in title.lower() or x in summary.lower() for x in ["上游", "供应", "涨价"]):
                signal_type = SignalType.SUPPLY_CHAIN
            elif any(x in title.lower() or x in summary.lower() for x in ["竞品", "对手", "同行"]):
                signal_type = SignalType.COMPETITOR
            
            if signal_type:
                signal_data = {
                    "type": signal_type.value,
                    "product_id": "",
                    "product_name": title[:30],
                    "level": item.get("level", "B"),
                    "sources": [source],
                    "confidence": item.get("confidence", item.get("credibility", 0.7) * 100),
                }
                
                action = self.process_signal(signal_data)
                if action:
                    actions.append(action)
        
        # 3. 去重（相同产品+相同动作类型）
        seen = set()
        unique_actions = []
        for action in actions:
            key = (action.product_id, action.action_type)
            if key not in seen:
                seen.add(key)
                unique_actions.append(action)
        
        # 4. 排序（按置信度和级别）
        unique_actions.sort(
            key=lambda x: (-x.confidence_score, x.signal_type)
        )
        
        return unique_actions[:20]  # 最多返回20条
    
    def save_actions(self, actions: List[ActionItem]):
        """保存动作到历史存档"""
        self.action_archive["actions"] = [
            action.to_dict() for action in actions
        ] + self.action_archive.get("actions", [])[:100]  # 保留最近100条
        self._save_action_archive()


def load_json(path):
    """加载JSON文件"""
    if not Path(path).exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def main():
    """测试入口"""
    engine = ActionEngine()
    
    # 加载日报payload
    payload_file = DATA_DIR / "daily_report_payload.json"
    if payload_file.exists():
        payload = load_json(payload_file)
        actions = engine.generate_actions_from_payload(payload)
        
        print(f"生成了 {len(actions)} 条动作建议：")
        for i, action in enumerate(actions, 1):
            print(f"\n{i}. {action.product_name}")
            print(f"   信号类型: {action.signal_type}")
            print(f"   动作类型: {action.action_type}")
            print(f"   方向: {action.direction}")
            print(f"   置信度: {action.confidence_level} ({action.confidence_score}%)")
            print(f"   建议: {action.suggested_adjustment}")
            print(f"   召回画像: {action.recall_profile_match or '无'}")
            print(f"   自动确认: {'是' if action.auto_confirm else '需人工确认'}")
        
        # 保存
        engine.save_actions(actions)
        print(f"\n已保存到 {ACTION_ARCHIVE_FILE}")
    else:
        print("未找到日报payload文件")


if __name__ == "__main__":
    main()
