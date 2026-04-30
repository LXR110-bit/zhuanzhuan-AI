#!/usr/bin/env python3
"""
告警通知模块 v2.6
功能：企业微信Webhook告警、持久化去重、可配置冷却、连续确认、异动归档
"""
import os
import json
import argparse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = BASE_DIR / "config"
THRESHOLDS_FILE = CONFIG_DIR / "thresholds.json"
ANOMALY_VOTES_FILE = DATA_DIR / "anomaly_votes.json"
DEFAULT_STATE_FILE = DATA_DIR / "alert_dedup_state.json"
DEFAULT_ARCHIVE_DIR = DATA_DIR / "anomaly_votes_archive"


def _load_json(path):
    if not Path(path).exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _load_dedup_config():
    thresholds = _load_json(THRESHOLDS_FILE)
    return thresholds.get("alert_dedup", {})


@dataclass
class AlertConfig:
    webhook_url: str = ""
    error_threshold: int = 3
    cooldown_minutes: int = 30
    message_type: str = "text"


class AlertManager:
    def __init__(self, config: AlertConfig, state_file=None):
        self.config = config
        self._error_counts: dict = defaultdict(int)
        self._last_alert: dict = {}
        self._state_file = Path(state_file) if state_file else None
        self._dedup_config = _load_dedup_config()
        self._state = self._load_state()

    def _load_state(self):
        if self._state_file is None:
            return {"cooldowns": {}, "consecutive_detections": {}, "error_counts": {}}
        raw = _load_json(self._state_file)
        if not raw:
            return {"cooldowns": {}, "consecutive_detections": {}, "error_counts": {}}
        self._error_counts = defaultdict(int, raw.get("error_counts", {}))
        return raw

    def _save_state(self):
        if self._state_file is None:
            return
        self._state["updated_at"] = datetime.now().isoformat()
        self._state["error_counts"] = dict(self._error_counts)
        _save_json(self._state_file, self._state)

    def _get_cooldown_minutes(self, level="ALERT"):
        by_level = self._dedup_config.get("cooldown_by_level", {})
        return by_level.get(level, self._dedup_config.get(
            "default_cooldown_minutes", self.config.cooldown_minutes))

    def _can_alert(self, key: str, level: str = "ALERT") -> bool:
        if self._state_file is None:
            last = self._last_alert.get(key)
            if last is None:
                return True
            elapsed = (datetime.now() - last).total_seconds() / 60
            return elapsed >= self.config.cooldown_minutes

        cooldowns = self._state.get("cooldowns", {})
        entry = cooldowns.get(key)
        if entry is None:
            return True
        last_str = entry.get("last_alert_at")
        if not last_str:
            return True
        try:
            last_dt = datetime.fromisoformat(last_str)
        except (ValueError, TypeError):
            return True
        elapsed = (datetime.now() - last_dt).total_seconds() / 60
        return elapsed >= self._get_cooldown_minutes(level)

    def _record_cooldown(self, key: str, level: str, change_pct=None):
        if self._state_file is None:
            self._last_alert[key] = datetime.now()
            return
        cooldowns = self._state.setdefault("cooldowns", {})
        entry = cooldowns.get(key, {})
        entry["last_alert_at"] = datetime.now().isoformat()
        entry["cooldown_minutes"] = self._get_cooldown_minutes(level)
        entry["alert_count"] = entry.get("alert_count", 0) + 1
        entry["last_signal_type"] = level
        if change_pct is not None:
            entry["last_change_pct"] = change_pct
        cooldowns[key] = entry
        self._save_state()

    def _check_consecutive(self, product_key: str, detection_info=None) -> bool:
        required = self._dedup_config.get("consecutive_confirmation_required", 2)
        if required <= 1 or self._state_file is None:
            return True

        consec = self._state.setdefault("consecutive_detections", {})
        entry = consec.get(product_key, {})
        count = entry.get("count", 0) + 1
        now_str = datetime.now().isoformat()
        entry["count"] = count
        if count == 1:
            entry["first_detected_at"] = now_str
        entry["last_detected_at"] = now_str
        entry["confirmed"] = count >= required
        consec[product_key] = entry
        self._save_state()
        return count >= required

    def _reset_consecutive(self, product_key: str):
        consec = self._state.get("consecutive_detections", {})
        if product_key in consec:
            del consec[product_key]
            self._save_state()

    def _send(self, title: str, content: str, level: str = "warning") -> bool:
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

    def on_error(self, source: str, error: Exception) -> bool:
        self._error_counts[source] += 1
        count = self._error_counts[source]

        if count >= self.config.error_threshold and self._can_alert(source, "WARN"):
            self._record_cooldown(source, "WARN")
            return self._send(
                title=f"🚨 任务告警 - {source}",
                content=f"**连续错误 {count} 次**\n\n错误信息: `{str(error)[:200]}`",
                level="error"
            )
        return False

    def on_success(self, source: str) -> bool:
        if self._error_counts[source] >= self.config.error_threshold:
            self._error_counts[source] = 0
            self._save_state()
            return self._send(
                title=f"✅ 任务恢复 - {source}",
                content="服务已恢复正常",
                level="info"
            )
        self._error_counts[source] = 0
        return False

    def on_data_anomaly(self, keyword: str, count: int, expected_min: int = 10) -> bool:
        key = f"data_{keyword}"
        if count < expected_min and self._can_alert(key, "WARN"):
            self._record_cooldown(key, "WARN")
            return self._send(
                title=f"⚠️ 数据量异常 - {keyword}",
                content=f"抓取数量 **{count}** 低于预期最小值 {expected_min}，可能触发反爬",
                level="warning"
            )
        return False

    def on_price_anomaly(self, product: str, price_change: float, threshold: float = 0.15) -> bool:
        if abs(price_change) < threshold:
            return False
        key = f"price_{product}"
        level = "CRITICAL" if abs(price_change) >= 0.30 else "ALERT"
        if not self._check_consecutive(key):
            return False
        if not self._can_alert(key, level):
            return False
        self._record_cooldown(key, level, change_pct=round(price_change * 100, 1))
        self._reset_consecutive(key)
        direction = "暴跌" if price_change < 0 else "暴涨"
        return self._send(
            title=f"⚠️ 价格异动 - {product}",
            content=f"价格{direction} **{abs(price_change)*100:.1f}%**，超过阈值 {threshold*100:.0f}%",
            level="warning" if price_change > 0 else "error"
        )

    def on_price_drop_alert(
        self,
        product: str,
        baseline_price: str,
        current_price: str,
        change_pct: str,
        baseline_date: str = None,
        current_date: str = None
    ) -> bool:
        baseline_label = baseline_date if baseline_date else "历史数据"
        current_label = current_date if current_date else "今日"

        bp = f"{baseline_price}元" if baseline_price and not baseline_price.endswith("元") else baseline_price or "未知"
        cp = f"{current_price}元" if current_price and not current_price.endswith("元") else current_price or "未知"

        if baseline_date:
            content = f"**{product}**: {bp}（{baseline_date}）→ {cp}（{current_label}），跌幅 {change_pct}"
        else:
            content = f"**{product}**: 原均价 {bp} → 当前 {cp}，跌幅 {change_pct}"

        return self._send(
            title=f"🚨 价格下跌告警 - {product}",
            content=content,
            level="error"
        )

    def on_scenario_alert(self, scenario: str, product: str, details: str) -> bool:
        return self._send(
            title=f"📊 市场场景 - {product}",
            content=f"**场景**: {scenario}\n\n{details}",
            level="warning"
        )

    @staticmethod
    def archive_anomaly_votes(votes_file=None, archive_dir=None):
        votes_file = Path(votes_file) if votes_file else ANOMALY_VOTES_FILE
        config = _load_dedup_config()
        archive_dir = Path(archive_dir) if archive_dir else Path(
            BASE_DIR / config.get("archive_dir", "data/anomaly_votes_archive"))
        max_days = config.get("max_archive_days", 60)

        votes = _load_json(votes_file)
        if not votes or not votes.get("items"):
            return {"archived": False, "reason": "no_votes_to_archive"}

        today = datetime.now().strftime("%Y-%m-%d")
        archive_file = archive_dir / f"{today}.json"

        existing = _load_json(archive_file)
        if existing and existing.get("items"):
            existing["items"].extend(votes.get("items", []))
            existing["archived_at"] = datetime.now().isoformat()
        else:
            existing = {
                "version": "1.0.0",
                "date": today,
                "archived_at": datetime.now().isoformat(),
                "items": votes.get("items", []),
            }

        items = existing["items"]
        by_level = defaultdict(int)
        for item in items:
            lvl = item.get("level", "INFO")
            by_level[lvl] += 1
        existing["summary"] = {
            "total": len(items),
            **{k: v for k, v in sorted(by_level.items())},
        }
        _save_json(archive_file, existing)

        _cleanup_old_archives(archive_dir, max_days)
        return {"archived": True, "file": str(archive_file), "items": len(items)}


def _cleanup_old_archives(archive_dir, max_days):
    archive_dir = Path(archive_dir)
    if not archive_dir.exists():
        return
    cutoff = datetime.now().strftime("%Y-%m-%d")
    from datetime import timedelta
    cutoff_date = (datetime.now() - timedelta(days=max_days)).strftime("%Y-%m-%d")
    for f in sorted(archive_dir.glob("*.json")):
        if f.stem < cutoff_date:
            f.unlink(missing_ok=True)


DEFAULT_WEBHOOK = os.environ.get("WECOM_WEBHOOK_URL", "")
default_alert = AlertManager(
    AlertConfig(webhook_url=DEFAULT_WEBHOOK),
    state_file=str(DEFAULT_STATE_FILE),
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行情追踪告警工具")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("test", help="发送一条测试告警")
    subparsers.add_parser("archive-votes", help="归档当前 anomaly_votes.json")
    parser.add_argument("--webhook-url", default=DEFAULT_WEBHOOK)
    args = parser.parse_args()

    if args.command == "test":
        alert = AlertManager(
            AlertConfig(webhook_url=args.webhook_url, error_threshold=1),
            state_file=str(DEFAULT_STATE_FILE),
        )
        sent = alert._send("测试告警", "这是一条测试消息", "info")
        print(json.dumps({"ok": True, "sent": sent}, ensure_ascii=False, indent=2))
    elif args.command == "archive-votes":
        result = AlertManager.archive_anomaly_votes()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
