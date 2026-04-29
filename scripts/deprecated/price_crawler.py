#!/usr/bin/env python3
"""
价格爬取：爱回收、闲鱼
支持产品：Pocket 3, Pocket 4, RTX 3070, RTX 4070, i5 13600K
"""
import os
import argparse
import json
import time
import random
import re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from safe_storage import SafeJsonStorage

SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
PID_FILE = DATA_DIR / "crawler.pid"
PROGRESS_FILE = DATA_DIR / "progress.json"

PRODUCTS = [
    {"id": "pocket3", "name": "DJI Pocket 3", "keywords": ["大疆 Pocket 3", "DJI Pocket 3"]},
    {"id": "pocket4", "name": "DJI Pocket 4", "keywords": ["大疆 Pocket 4", "DJI Pocket 4"]},
    {"id": "rtx3070", "name": "RTX 3070", "keywords": ["RTX 3070", "3070显卡"]},
    {"id": "rtx4070", "name": "RTX 4070", "keywords": ["RTX 4070", "4070显卡"]},
    {"id": "i5_13600k", "name": "i5-13600K", "keywords": ["i5 13600K", "13600K"]},
]

PLATFORMS = ["aihuishou", "xianyu"]


@dataclass
class PriceRecord:
    product_id: str
    product_name: str
    platform: str
    price: Optional[float]
    condition: str
    source_url: str
    crawl_time: str
    status: str

    def to_dict(self):
        return asdict(self)


class BaseCrawler:
    """爬虫基类"""
    platform = "base"
    base_delay = (2, 5)

    def __init__(self):
        self.session = self._build_session()

    def _build_session(self):
        try:
            import requests
            s = requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            return s
        except ImportError:
            return None

    def random_delay(self):
        time.sleep(random.uniform(*self.base_delay))

    def fetch_price(self, product: dict) -> PriceRecord:
        raise NotImplementedError


class AihuishouCrawler(BaseCrawler):
    """爱回收爬虫"""
    platform = "aihuishou"
    base_delay = (3, 7)

    def fetch_price(self, product: dict) -> PriceRecord:
        keyword = product["keywords"][0]
        url = f"https://www.aihuishou.com/search?keyword={keyword}"
        try:
            self.random_delay()
            if self.session is None:
                raise ImportError("requests not installed")
            resp = self.session.get(url, timeout=15)
            if "会员" in resp.text or resp.status_code == 403:
                return PriceRecord(
                    product_id=product["id"], product_name=product["name"],
                    platform=self.platform, price=None, condition="",
                    source_url=url, crawl_time=self._now(), status="blocked"
                )
            price = self._parse_price(resp.text)
            status = "success" if price is not None else "no_price"
            return PriceRecord(
                product_id=product["id"], product_name=product["name"],
                platform=self.platform, price=price, condition="回收价",
                source_url=url, crawl_time=self._now(), status=status
            )
        except Exception as e:
            return PriceRecord(
                product_id=product["id"], product_name=product["name"],
                platform=self.platform, price=None, condition="",
                source_url=url, crawl_time=self._now(), status=f"failed:{e}"
            )

    def _parse_price(self, html: str) -> Optional[float]:
        match = re.search(r'price["\s:]+(\d+\.?\d*)', html)
        return float(match.group(1)) if match else None

    def _now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class XianyuCrawler(BaseCrawler):
    """闲鱼爬虫 - 二手市场价"""
    platform = "xianyu"
    base_delay = (3, 8)

    def fetch_price(self, product: dict) -> PriceRecord:
        keyword = product["keywords"][0]
        url = f"https://s.goofish.com/search?q={keyword}"
        try:
            self.random_delay()
            if self.session is None:
                raise ImportError("requests not installed")
            resp = self.session.get(url, timeout=15)
            price = self._parse_median_price(resp.text)
            status = "success" if price is not None else "no_price"
            return PriceRecord(
                product_id=product["id"], product_name=product["name"],
                platform=self.platform, price=price, condition="二手中位价",
                source_url=url, crawl_time=self._now(), status=status
            )
        except Exception as e:
            return PriceRecord(
                product_id=product["id"], product_name=product["name"],
                platform=self.platform, price=None, condition="",
                source_url=url, crawl_time=self._now(), status=f"failed:{e}"
            )

    def _parse_median_price(self, html: str) -> Optional[float]:
        prices = [float(p) for p in re.findall(r'(\d{2,5}\.?\d{0,2})\s*元', html)]
        prices = [p for p in prices if p >= 1]
        if not prices:
            return None
        prices.sort()
        mid = len(prices) // 2
        return prices[mid]

    def _now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class PriceCrawlerEngine:
    """爬取调度引擎"""

    def __init__(self):
        self.crawlers = {
            "aihuishou": AihuishouCrawler(),
            "xianyu": XianyuCrawler(),
        }
        self.results: List[PriceRecord] = []
        self.storage = SafeJsonStorage(str(DATA_DIR))

    def run_full_cycle(self):
        """完整爬取一轮"""
        self._write_progress("执行中", "crawl_started")
        for product in PRODUCTS:
            for platform_name, crawler in self.crawlers.items():
                record = crawler.fetch_price(product)
                self.results.append(record)
                print(f"  [{record.status}] {record.product_name} @ {platform_name}: {record.price}")
        self._write_progress("执行中", "crawl_finished")

    def save_results(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = DATA_DIR / f"prices_{timestamp}.json"
        data = [r.to_dict() for r in self.results]
        output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(f"已保存 {len(data)} 条记录 -> {output_file}")

        # 同时更新 latest.json
        latest = DATA_DIR / "latest.json"
        latest.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        self._save_price_cache(data)
        self._write_progress("已完成", "price_cache_updated")

    def _write_progress(self, status: str, stage: str):
        progress = {
            "version": "1.0.0",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "updated_at": datetime.now().isoformat(),
            "任务元信息": {
                "状态": status,
                "最后更新时间": datetime.now().isoformat(),
                "当前阶段": stage,
            },
            "机型状态": {
                r.product_id: {
                    "状态": r.status,
                    "平台": r.platform,
                    "价格": r.price,
                    "更新时间": r.crawl_time,
                }
                for r in self.results
            },
        }
        tmp_path = PROGRESS_FILE.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(PROGRESS_FILE)

    def run_once(self):
        """执行一轮后退出，适合日程任务。"""
        PID_FILE.write_text(str(os.getpid()))
        try:
            self.results = []
            self.run_full_cycle()
            self.save_results()
        finally:
            PID_FILE.unlink(missing_ok=True)

    def _save_price_cache(self, records: List[dict]):
        """将抓取结果标准化写入统一缓存。"""
        now = datetime.now()
        scan_time = now.strftime("%Y-%m-%d")

        prices: Dict[str, dict] = {}
        for record in records:
            product_id = record["product_id"]
            product = prices.setdefault(
                product_id,
                {
                    "product_id": product_id,
                    "product_name": record["product_name"],
                    "updated_at": record["crawl_time"],
                    "platforms": {},
                    "aihuishou": {},
                    "xianyu_market": {},
                    "latest_prices": {},
                },
            )

            platform_data = {
                "price": record["price"],
                "condition": record["condition"],
                "source_url": record["source_url"],
                "crawl_time": record["crawl_time"],
                "status": record["status"],
            }
            platform = record["platform"]
            product["platforms"][platform] = platform_data
            product["updated_at"] = max(product["updated_at"], record["crawl_time"])

            if platform == "aihuishou":
                product["aihuishou"] = {
                    "tansuo_price": record["price"],
                    "last_crawl": record["crawl_time"],
                    "status": record["status"],
                    "source_url": record["source_url"],
                }
                product["latest_prices"]["recycle_price"] = record["price"]
            elif platform == "xianyu":
                product["xianyu_market"] = {
                    "avg": record["price"],
                    "last_crawl": record["crawl_time"],
                    "status": record["status"],
                    "source_url": record["source_url"],
                }
                product["latest_prices"]["market_price"] = record["price"]
        price_cache = {
            "version": "0.1.0",
            "updated_at": now.isoformat(),
            "scan_time": scan_time,
            "source": "scripts/price_crawler.py",
            "prices": prices,
        }
        self.storage.save_json(price_cache, ".", "price_cache.json")
        print(f"已更新统一缓存 -> {DATA_DIR / 'price_cache.json'}")

    def run_loop(self, interval: int = 3600):
        """持续运行模式"""
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
        print(f"爬虫启动, PID={os.getpid()}, 间隔={interval}s")
        try:
            while True:
                print(f"\n[{datetime.now()}] 开始爬取...")
                self.results = []
                self.run_full_cycle()
                self.save_results()
                print(f"下次爬取: {interval}s 后")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("爬虫手动停止")
        finally:
            PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["once", "loop"],
        default="once",
        help="默认 once：执行一轮后退出；loop：常驻循环",
    )
    parser.add_argument("--interval", type=int, default=3600)
    args = parser.parse_args()

    engine = PriceCrawlerEngine()
    if args.mode == "loop":
        engine.run_loop(interval=args.interval)
    else:
        engine.run_once()
