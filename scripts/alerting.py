#!/usr/bin/env python3
"""
告警通知模块
功能：企业微信Webhook告警、连续错误检测、数据异常告警
"""
import os
import json
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict


@dataclass
class AlertConfig:
    webhook_url: str = ""
    error_threshold: int = 3      # 连续错误次数触发告警
    cooldown_minutes: int = 30    # 告警冷却时间
    message_type: str = "text"    # text | markdown


class AlertManager:
    def __init__(self, config: AlertConfig):
        self.config = config
        self._error_counts: dict = defaultdict(int)
        self._last_alert: dict = {}
    
    def _send(self, title: str, content: str, level: str = "warning") -> bool:
        """发送到企业微信"""
        if not self.config.webhook_url:
            print("[Alert] 未配置 WECOM_WEBHOOK_URL，跳过发送")
            return False

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if self.config.message_type == "markdown":
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "content": f"## {title}\n\n{content}\n\n> {timestamp}"
                }
            }
        else:
            payload = {
                "msgtype": "text",
                "text": {
                    "content": f"{title}\n\n{content}\n\n{timestamp}"
                }
            }
        
        try:
            req = urllib.request.Request(
                self.config.webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            print(f"[Alert] 发送失败: {e}")
            return False
    
    def _can_alert(self, key: str) -> bool:
        last = self._last_alert.get(key)
        if last is None:
            return True
        elapsed = (datetime.now() - last).total_seconds() / 60
        return elapsed >= self.config.cooldown_minutes
    
    def on_error(self, source: str, error: Exception) -> bool:
        """记录错误，达到阈值时告警"""
        self._error_counts[source] += 1
        count = self._error_counts[source]
        
        if count >= self.config.error_threshold and self._can_alert(source):
            self._last_alert[source] = datetime.now()
            return self._send(
                title=f"🚨 任务告警 - {source}",
                content=f"**连续错误 {count} 次**\n\n错误信息: `{str(error)[:200]}`",
                level="error"
            )
        return False
    
    def on_success(self, source: str) -> bool:
        """成功后重置计数，恢复通知"""
        if self._error_counts[source] >= self.config.error_threshold:
            self._error_counts[source] = 0
            return self._send(
                title=f"✅ 任务恢复 - {source}",
                content="服务已恢复正常",
                level="info"
            )
        self._error_counts[source] = 0
        return False
    
    def on_data_anomaly(self, keyword: str, count: int, expected_min: int = 10) -> bool:
        """数据量异常告警"""
        if count < expected_min and self._can_alert(f"data_{keyword}"):
            self._last_alert[f"data_{keyword}"] = datetime.now()
            return self._send(
                title=f"⚠️ 数据量异常 - {keyword}",
                content=f"抓取数量 **{count}** 低于预期最小值 {expected_min}，可能触发反爬",
                level="warning"
            )
        return False
    
    def on_price_anomaly(self, product: str, price_change: float, threshold: float = 0.15) -> bool:
        """价格异动告警"""
        if abs(price_change) >= threshold and self._can_alert(f"price_{product}"):
            self._last_alert[f"price_{product}"] = datetime.now()
            direction = "暴跌" if price_change < 0 else "暴涨"
            return self._send(
                title=f"⚠️ 价格异动 - {product}",
                content=f"价格{direction} **{abs(price_change)*100:.1f}%**，超过阈值 {threshold*100:.0f}%",
                level="warning" if price_change > 0 else "error"
            )
        return False
    
    def on_scenario_alert(self, scenario: str, product: str, details: str) -> bool:
        """市场场景告警"""
        return self._send(
            title=f"📊 市场场景 - {product}",
            content=f"**场景**: {scenario}\n\n{details}",
            level="warning"
        )


# 默认告警管理器（使用环境变量，避免把Webhook写进代码）
DEFAULT_WEBHOOK = os.environ.get("WECOM_WEBHOOK_URL", "")
default_alert = AlertManager(AlertConfig(webhook_url=DEFAULT_WEBHOOK))


if __name__ == "__main__":
    # 测试
    alert = AlertManager(AlertConfig(webhook_url=DEFAULT_WEBHOOK, error_threshold=1))
    alert._send("测试告警", "这是一条测试消息", "info")
