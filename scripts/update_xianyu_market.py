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


BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = BASE_DIR / "data" / "price_cache.json"


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
    
    # 保存旧价格作为prev_price，用于下次对比和审计
    if old_price != new_price and old_price > 0:
        product[platform]["prev_price"] = old_price
    
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
    parser.add_argument("--cache", type=str, default=str(DEFAULT_CACHE_PATH), help="price_cache.json路径")
    parser.add_argument("--skip-validation", action="store_true", help="跳过行情价合理性校验，强制写入")
    
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
    
    # 过滤0值、负值和明显异常低价（爱回收等平台返回0/极低价表示无法估价，不应覆盖旧数据）
    MIN_PRICE_BY_PRODUCT = {
        "dji_mini4_pro": 500,   # 低于500视为异常（爱回收¥2等）
        "dji_pocket3": 500,
        "rtx_4070": 500,
        "rtx_3070": 400,
        "rtx_3060": 300,
        "i5_13600k": 200,
        "i7_13700k": 300,
        "ddr5_16g": 50,
        "ddr5_32g": 80,
        "dji_mini3": 400,
        "dji_mini4": 400,
        "xiaomi_band10": 30,
        "xiaomi_band9": 20,
    }
    def is_valid_price(product_id, price):
        if price is None or price <= 0:
            return False
        min_price = MIN_PRICE_BY_PRODUCT.get(product_id, 1)
        if price < min_price:
            print(f"  ⚠️  {product_id} 价格 ¥{price} 低于最低阈值 ¥{min_price}，视为异常低价跳过")
            return False
        return True
    
    filtered = {k: v for k, v in prices.items() if is_valid_price(k, v)}
    skipped = {k: v for k, v in prices.items() if v is None or v <= 0}
    if skipped:
        print(f"⚠️  跳过{len(skipped)}个无效价格（≤0或null）：{list(skipped.keys())}")
    
    if not filtered:
        print("❌ 所有价格均为0或null，不更新cache")
        sys.exit(0)
    
    print(f"\n📊 价格更新脚本 ({args.platform})")
    print(f"=" * 50)
    print(f"待更新产品数: {len(filtered)}（原始{len(prices)}个，过滤{len(skipped)}个）")
    print(f"-" * 50)
    
    # 读取cache
    cache_path = Path(args.cache)
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
    except Exception as e:
        print(f"❌ 读取cache失败: {e}")
        sys.exit(1)
    
    # 行情价合理性校验（Opus方案B - 校验层）
    # 行情价应该 ≥ 官方回收价，如果低于说明可能取错了数据源
    def validate_market_price(product_id, new_price, cache_data, platform):
        """校验行情价合理性，返回 (is_valid, reason)"""
        if platform != "xianyu_market":
            return True, "非行情价，跳过校验"
        
        product = cache_data.get("prices", {}).get(product_id, {})
        if not product:
            return True, "新产品无基线，跳过校验"
        
        # 校验1：行情价不应低于闲鱼官方回收价（C2C市场价≥官方回收价是基本常识）
        # 如果行情价低于官方回收价，几乎可以确定取的是搜索列表价而非行情tab价
        xo_price = product.get("xianyu_official", {}).get("price")
        if xo_price and xo_price > 0 and new_price < xo_price * 0.85:
            return False, f"行情价¥{new_price}低于官方回收价¥{xo_price}的85%，疑似取错数据源（搜索列表价而非行情tab价）"
        
        # 校验2：行情价不应低于爱回收价（同理，C2C市场价≥回收价）
        ah_price = product.get("aihuishou", {}).get("base_price")
        if ah_price and ah_price > 0 and new_price < ah_price * 0.85:
            return False, f"行情价¥{new_price}低于爱回收价¥{ah_price}的85%，疑似取错数据源"
        
        # 校验3：日环比不应超过±50%（正常行情不会一天波动50%）
        prev_price = product.get("xianyu_market", {}).get("prev_price") or product.get("xianyu_market", {}).get("price")
        if prev_price and prev_price > 0:
            change = abs(new_price - prev_price) / prev_price
            if change > 0.5:
                return False, f"日环比{change:+.1%}超过±50%，疑似异常（前值¥{prev_price}→新值¥{new_price}）"
        
        return True, "校验通过"
    
    # 更新每个产品
    updated_products = []
    for product_id, new_price in filtered.items():
        # 写入前校验
        if not args.skip_validation:
            is_valid, reason = validate_market_price(product_id, new_price, cache_data, args.platform)
            if not is_valid:
                print(f"  🚫 {product_id} 校验失败: {reason}")
                print(f"     如确认价格正确，请使用 --skip-validation 参数强制写入")
                continue
            else:
                print(f"  ✅ {product_id} 校验通过: {reason}")
        
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
