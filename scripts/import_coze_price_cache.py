#!/usr/bin/env python3
"""Import the original Coze price cache into the current unified price_cache."""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = BASE_DIR / "扣子原价格爬取功能" / "白天异动检测_价格缓存.json"
OUTPUT_FILE = BASE_DIR / "data" / "price_cache.json"
CATEGORIES_FILE = BASE_DIR / "config" / "categories.json"


MANUAL_ID_MAP = {
    "RTX 3060": "rtx_3060",
    "RTX 3070": "rtx_3070",
    "RTX 3080": "rtx_3080",
    "RTX 3090": "rtx_3090",
    "RTX 4070": "rtx_4070",
    "RTX 4080": "rtx_4080",
    "i5 13600K": "i5_13600k",
    "i7 13700K": "i7_13700k",
    "5600X": "r5_5600x",
    "5800X3D": "r7_5800x3d",
    "DJI Pocket 3": "dji_pocket3",
    "DJI Pocket 4": "dji_pocket4",
    "DJI Action 5": "dji_action5",
    "DJI Action 6": "dji_action6",
    "insta360 X4": "insta360_x4",
    "insta360 X5": "insta360_x5",
    "insta360 Ace Pro": "insta360_acepro",
    "DDR5内存": "ddr5_16g",
    "NAND固态": "nand_ssd",
    "小米手环9": "xiaomi_band9",
    "小米手环10": "xiaomi_band10",
}


def now_iso():
    return datetime.now().isoformat()


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def load_json(path):
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def as_number(value):
    if value in (None, "", "-", "—", "TBD"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize(text):
    return re.sub(r"[\s_\-]+", "", str(text or "").lower())


def category_name_map():
    data = load_json(CATEGORIES_FILE)
    mapping = {}
    for category in (data.get("categories") or {}).values():
        for item in category.get("items") or []:
            item_id = item.get("id")
            names = [item.get("name")] + (item.get("search_keywords") or [])
            for name in names:
                if name and item_id:
                    mapping[normalize(name)] = item_id
    return mapping


def resolve_product_id(name, name_map):
    if name in MANUAL_ID_MAP:
        return MANUAL_ID_MAP[name]
    norm = normalize(name)
    if norm in name_map:
        return name_map[norm]
    return norm or name


def platform_block(price, source, updated_at, status):
    return {
        "price": price,
        "source": source,
        "last_crawl": updated_at,
        "status": status,
    }


def build_price_cache(source_data):
    name_map = category_name_map()
    prices = {}
    for product_name, item in (source_data.get("prices") or {}).items():
        product_id = resolve_product_id(product_name, name_map)
        updated_at = item.get("last_update") or source_data.get("updated_at") or today_str()
        market_price = as_number(item.get("market_price"))
        xianyu_official = as_number(item.get("xianyu_official"))
        aihuishou = as_number(item.get("aihuishou"))
        status = item.get("status") or "cached"

        prices[product_id] = {
            "product_id": product_id,
            "product_name": product_name,
            "updated_at": updated_at,
            "source": "coze_original_price_cache",
            "note": item.get("note"),
            "status": status,
            "platforms": {
                "xianyu_market": platform_block(market_price, "coze_search_web", updated_at, status),
                "xianyu_official": platform_block(xianyu_official, "coze_mobile_use", updated_at, status),
                "aihuishou": platform_block(aihuishou, "coze_mobile_use_or_search_web", updated_at, status),
            },
            "xianyu_market": {
                "avg": market_price,
                "last_crawl": updated_at,
                "status": status if market_price is not None else "no_price",
                "source": "coze_search_web",
            },
            "xianyu_official": {
                "price": xianyu_official,
                "last_crawl": updated_at,
                "status": status if xianyu_official is not None else "no_price",
                "source": "coze_mobile_use",
            },
            "aihuishou": {
                "tansuo_price": aihuishou,
                "last_crawl": updated_at,
                "status": status if aihuishou is not None else "no_price",
                "source": "coze_mobile_use_or_search_web",
            },
            "latest_prices": {
                "market_price": market_price,
                "official_recycle_price": xianyu_official,
                "recycle_price": aihuishou,
            },
        }

    return {
        "version": "0.2.0",
        "updated_at": now_iso(),
        "scan_time": today_str(),
        "source": str(DEFAULT_INPUT),
        "source_version": source_data.get("version"),
        "source_updated_at": source_data.get("updated_at"),
        "prices": prices,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(OUTPUT_FILE))
    args = parser.parse_args()

    source_data = load_json(Path(args.input))
    if not source_data:
        raise SystemExit(f"source cache missing or empty: {args.input}")

    cache = build_price_cache(source_data)
    save_json(Path(args.output), cache)
    valid_market = sum(
        1 for item in cache["prices"].values()
        if item.get("xianyu_market", {}).get("avg") is not None
    )
    print(json.dumps({
        "ok": True,
        "input": args.input,
        "output": args.output,
        "products": len(cache["prices"]),
        "valid_market_prices": valid_market,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
