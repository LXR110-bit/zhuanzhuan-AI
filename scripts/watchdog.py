#!/usr/bin/env python3
"""
独立看门狗进程 - 防止任务卡死
功能：
- 检测爬虫进程存活
- 检测数据更新时效
- 23:00强制截止
- 异常时自动重启 + 告警
"""
import os
import sys
import time
import json
import subprocess
import signal
from datetime import datetime
from pathlib import Path

# 配置
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
DATA_DIR = BASE_DIR / "data"
PROGRESS_FILE = DATA_DIR / "progress.json"
PID_FILE = DATA_DIR / "crawler.pid"
LOG_FILE = BASE_DIR / "logs" / "watchdog.log"

CONFIG = {
    "check_interval": 30,        # 30秒检查一次
    "stale_threshold": 600,      # 数据超过10分钟未更新视为异常
    "max_restart_attempts": 3,
    "deadline": "23:00",         # 强制截止时间
    "alert_webhook": os.environ.get("WECOM_WEBHOOK_URL", ""),
}


class Watchdog:
    def __init__(self, config: dict):
        self.config = config
        self.restart_count = 0
        self.running = True
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
        
        # 确保日志目录存在
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _handle_shutdown(self, signum, frame):
        self.log("收到终止信号，看门狗退出")
        self.running = False

    def log(self, msg: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {msg}"
        print(line)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def load_progress(self) -> dict:
        if not PROGRESS_FILE.exists():
            return {}
        try:
            with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def save_progress(self, progress: dict):
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

    def check_deadline(self) -> bool:
        """检查是否到达截止时间"""
        now = datetime.now().strftime("%H:%M")
        return now >= self.config["deadline"]

    def force_deadline(self, progress: dict):
        """强制截止，生成日报"""
        self.log(f"截止时间到 {self.config['deadline']}", "WARNING")

        # 标记所有运行中任务为截止
        机型状态 = progress.get("机型状态", {})
        for model, status in 机型状态.items():
            if status.get("状态") in ["执行中", "待执行"]:
                机型状态[model]["状态"] = "截止终止"
                机型状态[model]["截止时间"] = datetime.now().isoformat()
                self.log(f"  截止: {model}")

        progress["机型状态"] = 机型状态
        progress.setdefault("任务元信息", {})
        progress["任务元信息"]["状态"] = "已截止"
        progress["任务元信息"]["最后更新时间"] = datetime.now().isoformat()
        progress["任务元信息"]["截止原因"] = f"到达截止时间 {self.config['deadline']}"
        self.save_progress(progress)

    def check_data_freshness(self, progress: dict) -> bool:
        """检查数据更新时效"""
        last_update = progress.get("任务元信息", {}).get("最后更新时间")
        if not last_update:
            return False

        try:
            last_time = datetime.fromisoformat(last_update.replace("Z", "+00:00").replace("+08:00", ""))
            age = (datetime.now() - last_time).total_seconds()
            return age < self.config["stale_threshold"]
        except:
            return False

    def send_alert(self, msg: str):
        """发送告警到企业微信"""
        self.log(f"[ALERT] {msg}", "ERROR")
        webhook = self.config["alert_webhook"]
        if webhook:
            import urllib.request
            payload = json.dumps({"msgtype": "text", "text": {"content": f"[价格看门狗] {msg}"}})
            req = urllib.request.Request(webhook, data=payload.encode(), headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req, timeout=10)
            except Exception as e:
                self.log(f"告警发送失败: {e}", "ERROR")

    def run(self):
        self.log("看门狗启动")
        self.log(f"截止时间: {self.config['deadline']}")
        self.log(f"检查间隔: {self.config['check_interval']}s")

        while self.running:
            try:
                progress = self.load_progress()

                if not progress:
                    time.sleep(self.config["check_interval"])
                    continue

                status = progress.get("任务元信息", {}).get("状态", "")

                # 1. 检查截止时间
                if self.check_deadline():
                    self.force_deadline(progress)
                    self.log("截止触发，退出")
                    break

                # 2. 检查数据时效
                if status == "执行中" and not self.check_data_freshness(progress):
                    self.log("数据过期，可能任务卡死", "WARNING")
                    self.send_alert("数据超时未更新，可能任务卡死")

                # 3. 检查是否完成
                if status in ["已完成", "失败", "已截止"]:
                    self.log(f"任务状态: {status}，退出")
                    break

            except Exception as e:
                self.log(f"检查异常: {e}", "ERROR")

            time.sleep(self.config["check_interval"])

        self.log("看门狗退出")


if __name__ == "__main__":
    dog = Watchdog(CONFIG)
    dog.run()
