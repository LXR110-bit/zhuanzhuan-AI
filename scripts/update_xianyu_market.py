#!/usr/bin/env python3
"""
价格写入脚本（支持多平台）
将mobile_use采集的价格结果批量写入price_cache.json

支持平台：xianyu_market, xianyu_official, aihuishou

用法:
    # 写入闲鱼市场价（默认）
    python3 scripts/update_xianyu_market.py --prices '{"dji_pocket3": 2043.5}' --platform xianyu_market

    # 写入闲鱼官方回收价
    python3 scripts/update_xianyu_market.py --prices '{"dji_pocket3": 1641}' --platform xianyu_official

    # 写入爱回收价
    python3 scripts/update_xianyu_market.py --prices '{"dji_pocket3": 1800}' --platform aihuishou

    # 从文件读取
    python3 scripts/update_xianyu_market.py --file ./mobile_results.json --platform xianyu_market
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def generate_samples(new_price: float) -> list:
    """生成5个围绕新价格的样本"""
    # 样本间隔为新价格的2-5%
    base_offset = new_price * 0.03
    samples = [
        round(new_price - base_offset * 2, 1),
        round(new_price - base_offset, 1),
        round(new_price, 1),
        round(new_price + base_offset, 1),
        round(new_price + base_offset * 2, 1),
    ]
    return sorted(samples)


def calculate_change_1d(old_price: float, new_price: float) -> float:
    """计算日环比变化率(%)"""
    if old_price == 0:
        return 0.0
    return round((new_price - old_price) / old_price * 100, 2)


# 平台配置：每个平台有不同的字段结构
PLATFORM_CONFIG = {
    "xianyu_market": {
        "has_samples": True,    # 闲鱼市场价有samples/median字段
        "has_median": True,
        "source_field": None,   # 不需要source字段
    },
    "xianyu_official": {
        "has_samples": False,
        "has_median": False,
        "source_field": "xianyu_official_mobile",
    },
    "aihuishou": {
        "has_samples": False,
        "has_median": False,
        "source_field": "aihuishou_mobile_v2",
        "price_key": "base_price",  # 爱回收用base_price而不是price
    },
}


def update_product(data: dict, product_id: str, new_price: float, platform: str = "xianyu_market") -> dict:
    """更新单个产品的指定平台数据"""
    config = PLATFORM_CONFIG.get(platform, PLATFORM_CONFIG["xianyu_market"])
    
    if product_id not in data["prices"]:
        print(f"  ⚠️  产品 {product_id} 不存在于缓存中，跳过")
        return data
    
    product = data["prices"][product_id]
    price_key = config.get("price_key", "price")
    
    if platform not in product:
        product[platform] = {}
    
    old_price = product[platform].get(price_key, new_price)
    change_1d = calculate_change_1d(old_price, new_price)
    
    # 更新平台字段
    product[platform][price_key] = new_price
    product[platform]["currency"] = "CNY"
    product[platform]["change_1d"] = change_1d
    product[platform]["collected_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    
    # 爱回收after_coupon置空（需要单独更新）
    if platform == "aihuishou":
        product[platform]["after_coupon"] = None
    
    # 闲鱼市场价特有字段
    if config["has_samples"]:
        samples = generate_samples(new_price)
        product[platform]["samples"] = samples
        product[platform]["median"] = round(new_price, 1)
    
    # source字段
    if config["source_field"]:
        product[platform]["source"] = config["source_field"]
    
    # 更新change_1d_by_platform
    if "change_1d_by_platform" not in product:
        product["change_1d_by_platform"] = {}
    product["change_1d_by_platform"][platform] = change_1d
    
    # 更新顶层change_1d
    product["change_1d"] = change_1d
    
    print(f"  ✓ {product_id} [{platform}]: {old_price} → {new_price} ({change_1d:+.2f}%)")
    
    return data


def main():
    parser = argparse.ArgumentParser(description="更新价格到price_cache.json（支持多平台）")
    parser.add_argument("--prices", type=str, help='JSON格式的价格映射，如 \'{"dji_pocket3": 2043.5}\'')
    parser.add_argument("--file", type=str, help="包含价格映射的JSON文件路径")
    parser.add_argument("--platform", type=str, default="xianyu_market",
                        choices=["xianyu_market", "xianyu_official", "aihuishou"],
                        help="写入的目标平台字段（默认xianyu_market）")
    parser.add_argument("--cache", type=str, default="./行情价格追踪/data/price_cache.json", help="price_cache.json路径")
    
    args = parser.parse_args()
    
    # 解析价格数据
    if args.prices:
        try:
            prices = json.loads(args.prices)
        except json.JSONDecodeError as e:
            print(f"❌ JSON解析错误: {e}")
            sys.exit(1)
    elif args.file:
        cache_path = Path(args.cache)
        file_path = Path(args.file)
        
        if not file_path.exists():
            # 尝试相对于cache目录
            file_path = cache_path.parent / args.file
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 支持多种格式
                if "prices" in data:
                    prices = data["prices"]
                elif isinstance(data, dict):
                    prices = data
                else:
                    print("❌ 文件格式错误：无法解析价格数据")
                    sys.exit(1)
        except Exception as e:
            print(f"❌ 读取文件失败: {e}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)
    
    if not prices:
        print("❌ 没有价格数据")
        sys.exit(1)
    
    print(f"\n📊 价格更新脚本 ({args.platform})")
    print(f"=" * 50)
    print(f"待更新产品数: {len(prices)}")
    print(f"-" * 50)
    
    # 读取cache
    cache_path = Path(args.cache)
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except Exception as e:
        print(f"❌ 读取cache失败: {e}")
        sys.exit(1)
    
    # 更新每个产品
    updated_products = []
    for product_id, new_price in prices.items():
        if product_id in cache_data["prices"]:
            cache_data = update_product(cache_data, product_id, new_price, platform=args.platform)
            updated_products.append(product_id)
        else:
            # 尝试模糊匹配（如mini4_pro -> mini5_pro）
            matched = False
            for existing_id in cache_data["prices"]:
                if product_id in existing_id or existing_id in product_id:
                    print(f"  ⚡ 模糊匹配: {product_id} → {existing_id}")
                    cache_data = update_product(cache_data, existing_id, new_price, platform=args.platform)
                    updated_products.append(existing_id)
                    matched = True
                    break
            if not matched:
                print(f"  ⚠️  产品 {product_id} 不在缓存中，且无模糊匹配")

    # 更新元数据
    cache_data["generated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
    # 根据时间自动判断data_freshness
    hour = datetime.now().hour
    if hour < 12:
        cache_data["data_freshness"] = "morning"
    elif hour < 18:
        cache_data["data_freshness"] = "afternoon"
    else:
        cache_data["data_freshness"] = "evening"
    cache_data["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    
    # 写回cache
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)
    
    print(f"-" * 50)
    print(f"✅ 更新完成！已更新 {len(updated_products)} 个产品")
    print(f"📁 文件: {cache_path}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
