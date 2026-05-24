#!/usr/bin/env python3
"""Build the single daily report payload from current local data sources."""
import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from price_history_analyzer import build_all_products_history
from action_engine import ActionEngine
from runtime_logger import log_event, log_exception


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PRICE_CACHE_FILE = DATA_DIR / "price_cache.json"
CATEGORIES_FILE = BASE_DIR / "config" / "categories.json"
PAYLOAD_FILE = DATA_DIR / "daily_report_payload.json"
PUSH_STATUS_FILE = DATA_DIR / "push_status.json"
CLOUD_PC_DAILY_FILE = BASE_DIR / "cloud_pc_daily.json"
VALIDATION_REPORT_FILE = DATA_DIR / "validation_report.json"
ANOMALY_VOTES_FILE = DATA_DIR / "anomaly_votes.json"
NEWS_SIGNALS_FILE = DATA_DIR / "news_signals_filtered.json"
DAILY_PRICE_DIR = DATA_DIR / "daily_price_records"
DAILY_CATEGORY_LIMIT = 2


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def now_iso():
    return datetime.now().isoformat()


def parse_time(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    if text.endswith("Z"):
        try:
            return datetime.fromisoformat(text[:-1]).replace(tzinfo=None)
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def publish_time(item):
    return (
        item.get("published_at")
        or item.get("publish_time")
        or item.get("publish_date")
        or item.get("event_date")
    )


def load_json(path):
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid json: {path}: {exc}") from exc


def is_today_data(data, label):
    if not data:
        return False
    if data.get("date") == today_str():
        return True
    generated_at = str(data.get("generated_at") or data.get("updated_at") or "")
    return generated_at.startswith(today_str())


def load_today_json(path, label):
    data = load_json(path)
    if not data:
        return {}
    if is_today_data(data, label):
        return data
    log_event(
        "daily_payload.stale_input_skipped",
        label=label,
        path=str(path),
        date=data.get("date"),
        generated_at=data.get("generated_at"),
        updated_at=data.get("updated_at"),
    )
    return {}


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def fmt_price(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, (int, float)):
        return f"¥{value:g}"
    text = str(value)
    return text if text.startswith(("¥", "€", "$")) else text


def pct_text(value):
    if value in (None, ""):
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:+.1f}%"
    return str(value)


def platform_change_text(item, platform_key):
    changes = item.get("change_1d_by_platform") or {}
    value = changes.get(platform_key)
    return pct_text(value)


def nested_value(item, object_key, value_key):
    value = item.get(object_key)
    if isinstance(value, dict):
        return value.get(value_key)
    return value


def nested_first(item, object_key, value_keys):
    value = item.get(object_key)
    if not isinstance(value, dict):
        return value
    for key in value_keys:
        found = value.get(key)
        if found not in (None, "", "-", "—"):
            return found
    return None


def text_has_price(value):
    return value not in (None, "", "-", "—")


def category_entries(categories_data):
    categories = categories_data.get("categories") or {}
    if isinstance(categories, dict):
        return list(categories.items())
    if isinstance(categories, list):
        return [(item.get("name") or item.get("id") or f"品类{idx + 1}", item) for idx, item in enumerate(categories)]
    return []


def build_category_index(categories_data):
    product_to_category = {}
    ordered_categories = []
    for category_name, category in category_entries(categories_data):
        ordered_categories.append(category_name)
        for item in category.get("items") or []:
            product_id = item.get("id")
            if not product_id:
                continue
            product_to_category[product_id] = category_name
    return ordered_categories, product_to_category


def placeholder_row(product_id, item, category_name):
    return {
        "product_id": product_id,
        "model": item.get("name") or product_id,
        "category": category_name,
        "xianyu_market": "—",
        "xianyu_recycle": "—",
        "aihuishou": "—",
        "daily_change": "—",
        "platform_changes": {
            "xianyu_market": "—",
            "aihuishou": "—",
            "xianyu_official": "—",
        },
        "updated_at": None,
        "source": "category_config",
        "status": "missing",
        "missing_reason": "今日未获取到该代表机型价格",
        "baseline_date": "历史数据",
        "baseline_price": None,
    }


def select_daily_display_rows(rows, categories_data, per_category=DAILY_CATEGORY_LIMIT):
    """Daily card shows representative rows only; full scan count is kept in metadata."""
    if not categories_data:
        return rows[:12], {
            "mode": "fallback_first_rows",
            "categories": 0,
            "per_category": per_category,
            "display_rows": min(len(rows), 12),
            "total_rows": len(rows),
        }

    ordered_categories, product_to_category = build_category_index(categories_data)
    rows_by_id = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        product_id = row.get("product_id")
        if product_id:
            row["category"] = product_to_category.get(product_id, row.get("category") or "其他")
            rows_by_id[product_id] = row

    selected = []
    category_breakdown = []
    for category_name, category in category_entries(categories_data):
        category_rows = []
        for item in category.get("items") or []:
            product_id = item.get("id")
            if not product_id:
                continue
            row = rows_by_id.get(product_id)
            category_rows.append(row if row else placeholder_row(product_id, item, category_name))
            if len(category_rows) >= per_category:
                break
        selected.extend(category_rows)
        category_breakdown.append({
            "category": category_name,
            "rows": len(category_rows),
            "missing_rows": sum(1 for row in category_rows if row.get("status") == "missing"),
        })

    return selected, {
        "mode": "six_categories_two_models",
        "categories": len(ordered_categories),
        "per_category": per_category,
        "display_rows": len(selected),
        "total_rows": len(rows),
        "breakdown": category_breakdown,
    }


def latest_daily_price_file():
    if not DAILY_PRICE_DIR.exists():
        return None
    files = sorted(DAILY_PRICE_DIR.glob("*.json"))
    return files[-1] if files else None


def build_rows_from_price_cache(cache, validation_report=None):
    rows = []
    missing = []
    validation_products = (validation_report or {}).get("products", {})
    prices = cache.get("prices") or cache.get("models") or {}
    for cache_key, item in prices.items():
        product_id = item.get("id") or cache_key
        product_name = item.get("product_name") or item.get("name") or product_id
        xianyu_market = (
            nested_first(item, "xianyu_market", ("price", "median", "avg", "avg_price"))
            or item.get("xianyu_market_price")
            or item.get("闲鱼自由市场价格")
            or item.get("二手均价")
        )
        xianyu_recycle = (
            nested_value(item, "xianyu_official", "price")
            or item.get("xianyu_official_price")
            or item.get("闲鱼官方回收价格")
        )
        aihuishou = (
            nested_first(item, "aihuishou", ("tansuo_price", "after_coupon", "base_price"))
            or item.get("aihuishou_price")
            or item.get("爱回收价格")
        )
        zhuanzhuan = (
            nested_first(item, "zhuanzhuan_recycle", ("price",))
            or nested_first(item, "zhuanzhuan", ("price",))
            or item.get("zhuanzhuan_price")
            or item.get("转转回收价格")
        )
        updated = item.get("updated_at") or item.get("last_crawl") or item.get("verification_date")
        validation_item = validation_products.get(product_id) or validation_products.get(cache_key, {})
        platform_validation = validation_item.get("platforms", {})
        if platform_validation.get("xianyu_market", {}).get("reason"):
            xianyu_market = None
        if platform_validation.get("xianyu_official", {}).get("reason"):
            xianyu_recycle = None
        if platform_validation.get("aihuishou", {}).get("reason"):
            aihuishou = None

        # 读取 baseline_date 字段
        baseline_date = item.get("baseline_date") or "历史数据"

        if xianyu_market is None and xianyu_recycle is None and aihuishou is None:
            missing.append(f"{product_name}: 三价格缺失")
        for platform_key, label in (
            ("xianyu_market", "闲鱼自由市场价格"),
            ("xianyu_official", "闲鱼官方回收价"),
            ("aihuishou", "爱回收价"),
            ("zhuanzhuan_recycle", "转转回收价"),
        ):
            reason = platform_validation.get(platform_key, {}).get("reason")
            if reason:
                missing.append(f"{product_name} {label}: {reason}")

        rows.append({
            "product_id": product_id,
            "model": product_name,
            "xianyu_market": fmt_price(xianyu_market),
            "xianyu_recycle": fmt_price(xianyu_recycle),
            "aihuishou": fmt_price(aihuishou),
            "zhuanzhuan_recycle": fmt_price(zhuanzhuan),
            "daily_change": pct_text(item.get("change_1d") or item.get("change_percent")),
            "platform_changes": {
                "xianyu_market": platform_change_text(item, "xianyu_market"),
                "aihuishou": platform_change_text(item, "aihuishou"),
                "xianyu_official": platform_change_text(item, "xianyu_official"),
                "zhuanzhuan_recycle": platform_change_text(item, "zhuanzhuan_recycle"),
            },
            "updated_at": updated,
            "source": item.get("source", "price_cache"),
            "status": validation_item.get("status") or item.get("status", "cached"),
            "missing_reason": "；".join(
                platform.get("reason")
                for platform in platform_validation.values()
                if platform.get("reason")
            ),
            # 新增：原均价日期标注
            "baseline_date": baseline_date,
            "baseline_price": item.get("baseline_price") or item.get("二手均价"),
        })
    return rows, sorted(set(missing))


def row_has_price(row):
    return any(text_has_price(row.get(key)) for key in ("xianyu_market", "xianyu_recycle", "aihuishou", "zhuanzhuan_recycle"))


def build_rows_from_cloud_pc(data):
    rows = []
    for row in data.get("price_table", [])[:20]:
        rows.append({
            "product_id": row.get("机型", "").replace(" ", "_"),
            "model": row.get("机型", "-"),
            "xianyu_market": row.get("当前价格", "-"),
            "xianyu_recycle": "-",
            "aihuishou": "-",
            "zhuanzhuan_recycle": "-",
            "daily_change": row.get("变化", "-"),
            "updated_at": data.get("generated_at"),
            "source": "cloud_pc_daily",
            "status": row.get("趋势", "-"),
        })
    return rows


def normalize_signals(cloud_pc_data):
    signals = {"S": [], "A": [], "B": []}
    cloud_signals = cloud_pc_data.get("signals") or {}
    mapping = {"S级": "S", "A级": "A", "B级": "B"}
    for source_level, target_level in mapping.items():
        for item in cloud_signals.get(source_level, [])[:8]:
            title = item.get("产品") or item.get("title") or str(item)
            change = item.get("变化")
            signals[target_level].append({
                "title": f"{title} {change}".strip(),
                "source": "cloud_pc_daily",
                "raw": item,
            })
    return signals


def merge_news_signals(signals, news_data):
    relevance_keywords = (
        "rtx", "nvidia", "英伟达", "显卡", "矿卡", "矿潮",
        "ddr", "dram", "nand", "ssd", "内存", "固态", "存储",
        "dji", "大疆", "pocket", "action", "mini", "无人机",
        "insta360", "影石", "gopro", "运动相机", "拇指相机",
        "13600k", "13700k", "5600x", "5800x3d", "cpu",
        "小米手环", "智能手环", "手环",
        "爱回收", "回收价", "二手价格", "以旧换新",
    )
    irrelevant_keywords = (
        "废旧手机", "旧手机", "手机回收", "折叠屏手机", "iphone",
        "华强北手机", "碰撞概率", "概率碰撞", "至少碰撞", "无套路",
    )
    generic_titles = {"无标题", "未命名信号", "大家都在搜", "相关搜索"}
    cutoff = datetime.now() - timedelta(days=int(news_data.get("max_age_days") or 7))
    for item in (news_data.get("items") or [])[:20]:
        pub_time = parse_time(publish_time(item))
        if pub_time is None or pub_time < cutoff:
            continue
        if item.get("publish_time_quality") and item.get("publish_time_quality") != "platform_publish_time":
            continue
        level = item.get("level") or "B"
        if level not in signals:
            level = "B"
        title = item.get("title") or item.get("summary") or "未命名信号"
        summary_text = item.get("summary") or item.get("content") or item.get("description") or title
        source_url = item.get("url") or item.get("source_url") or item.get("link") or ""
        if not source_url.startswith(("http://", "https://")):
            continue
        cleaned_title = clean_signal_title(title)
        if cleaned_title in generic_titles or len(cleaned_title) < 4:
            continue
        if re.fullmatch(r"(\d+\s*(分钟前|小时前|天前)|昨天\s*\d{1,2}:\d{2}|前天\s*\d{1,2}:\d{2})", cleaned_title):
            continue
        relevance_text = f"{title} {summary_text} {item.get('query') or ''}".lower()
        if any(word.lower() in relevance_text for word in irrelevant_keywords):
            continue
        if not any(word.lower() in relevance_text for word in relevance_keywords):
            continue
        published_at = pub_time.strftime("%Y-%m-%d %H:%M:%S")
        publish_date = pub_time.strftime("%Y-%m-%d")
        raw_source = item.get("source") or "news_signals"
        signals[level].append({
            "title": cleaned_title,
            "summary": summary_text,
            "source": _display_source(raw_source),
            "url": source_url,
            "domain": item.get("domain") or "",
            "author": item.get("author") or "",
            "published_at": published_at,
            "publish_date": publish_date,
            "dedupe_key": item.get("dedupe_key"),
            "raw": item,
        })
    return signals


# product_id → 中文显示名
PRODUCT_DISPLAY_NAMES = {
    "dji_pocket3": "DJI Pocket 3", "dji_pocket4": "DJI Pocket 4",
    "dji_action5": "DJI Action 5", "dji_action6": "DJI Action 6",
    "insta360_x4": "insta360 X4", "insta360_x5": "insta360 X5",
    "insta360_acepro": "insta360 Ace Pro",
    "rtx_3060": "RTX 3060", "rtx_3070": "RTX 3070", "rtx_3080": "RTX 3080",
    "rtx_3090": "RTX 3090", "rtx_4060": "RTX 4060", "rtx_4070": "RTX 4070",
    "rtx_4080": "RTX 4080",
    "i5_13600k": "i5 13600K", "i7_13700k": "i7 13700K",
    "r5_5600x": "5600X", "r7_5800x3d": "5800X3D",
    "ddr5_16g": "DDR5 16G", "ddr5_32g": "DDR5 32G", "ddr4_16g": "DDR4 16G",
    "nand_ssd": "NAND 固态",
    "dji_mini3": "DJI Mini 3", "dji_mini4": "DJI Mini 4",
    "dji_mini4_pro": "DJI Mini 4 Pro", "dji_lito_x1": "DJI Lito X1",
    "xiaomi_band9": "小米手环 9", "xiaomi_band10": "小米手环 10",
}

# platform key → 中文显示名
PLATFORM_DISPLAY_NAMES = {
    "xianyu_market": "闲鱼市场",
    "xianyu_recycle": "闲鱼回收",
    "aihuishou": "爱回收",
}

# source → 中文显示名
SOURCE_DISPLAY_NAMES = {
    "anomaly_votes": "异动检测",
    "tikhub:douyin": "抖音",
    "tikhub:xiaohongshu": "小红书",
    "tikhub:bilibili": "B站",
    "tikhub:weibo": "微博",
}


def _display_product(product_id_or_name):
    """将 product_id 或 product_name 转为中文显示名"""
    return PRODUCT_DISPLAY_NAMES.get(product_id_or_name,
           PRODUCT_DISPLAY_NAMES.get(product_id_or_name.lower().replace(" ", "_"),
           product_id_or_name))


def _display_platform(platform_key):
    """将 platform key 转为中文显示名"""
    return PLATFORM_DISPLAY_NAMES.get(platform_key, platform_key)


def _display_source(source_key):
    """将 source key 转为中文显示名"""
    return SOURCE_DISPLAY_NAMES.get(source_key, source_key)


def clean_signal_title(title):
    """清理信号标题中的英文前缀"""
    if not title:
        return title
    prefixes = [
        "douyin signal: ", "Douyin signal: ",
        "bilibili signal: ", "Bilibili signal: ",
        "xiaohongshu signal: ", "Xiaohongshu signal: ",
        "weibo signal: ", "Weibo signal: ",
    ]
    for prefix in prefixes:
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title


def merge_anomaly_votes(signals, anomaly_votes):
    for item in (anomaly_votes.get("items") or [])[:20]:
        level = item.get("level", "B")
        if level not in signals:
            level = "B"
        change = item.get("change_pct")
        change_text = f"{change:+.1f}%" if isinstance(change, (int, float)) else str(change or "异动")
        product = _display_product(item.get('product_name') or item.get('product_id'))
        platform = _display_platform(item.get('platform'))
        title = f"{product} {platform} {change_text}"
        signals[level].append({
            "title": title,
            "source": _display_source("anomaly_votes"),
            "raw": item,
        })
    return signals


def summarize(rows, signals, missing, cloud_pc_data, news_data=None):
    signal_count = sum(len(v) for v in signals.values())
    valid_rows = [row for row in rows if isinstance(row, dict) and row_has_price(row)]
    if rows and not valid_rows:
        one_sentence = f"今日扫描{len(rows)}个价格项，但未获取到有效报价。"
    elif valid_rows and signal_count:
        one_sentence = f"今日监控{len(valid_rows)}个有效价格项，发现{signal_count}条需关注信号。"
    elif valid_rows:
        one_sentence = f"今日监控{len(valid_rows)}个有效价格项，暂未发现高优先级异动。"
    else:
        one_sentence = "今日暂无可用价格数据，需先完成价格扫描。"

    if signals["S"]:
        today_action = "优先核查S级信号对应机型，必要时即时告警。"
    elif signals["A"]:
        today_action = "关注A级信号，纳入10点日报和后续价格核查。"
    elif valid_rows:
        today_action = "按10点固定节奏推送图片日报，白天继续巡检。"
    elif rows:
        today_action = "先修复价格源连接，再重新执行价格扫描。"
    else:
        today_action = "先执行价格扫描或云电脑日报生成，再生成图片卡片。"

    quality_parts = []
    if rows:
        quality_parts.append(f"价格记录{len(rows)}条，有效{len(valid_rows)}条")
    else:
        quality_parts.append("价格记录为空")
    if missing:
        quality_parts.append(f"缺失{len(missing)}项")
    if cloud_pc_data:
        quality_parts.append("已合并云电脑日报")
    else:
        quality_parts.append("未发现云电脑日报")
    if news_data:
        summary = news_data.get("summary", {})
        quality_parts.append(f"资讯信号保留{summary.get('kept', 0)}条，去重/过期{summary.get('dropped', 0)}条")
    if missing:
        quality_parts.append("缺失项已标注原因")

    return {
        "one_sentence": one_sentence,
        "today_action": today_action,
        "data_quality": "；".join(quality_parts),
    }


def update_push_status(payload):
    status = load_json(PUSH_STATUS_FILE)
    if not status:
        return
    if status.get("date") != payload["date"]:
        status["date"] = payload["date"]
    status["updated_at"] = now_iso()
    daily = status.setdefault("daily_report", {})
    if daily.get("status") in (None, "pending", "not_generated"):
        daily["status"] = "payload_ready"
    daily["last_error"] = None
    save_json(PUSH_STATUS_FILE, status)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(PAYLOAD_FILE))
    args = parser.parse_args()
    log_event("daily_payload.start", output=args.output)

    price_cache = load_json(PRICE_CACHE_FILE)
    cloud_pc_data = load_today_json(CLOUD_PC_DAILY_FILE, "cloud_pc_daily")
    validation_report = load_today_json(VALIDATION_REPORT_FILE, "validation_report")
    anomaly_votes = load_today_json(ANOMALY_VOTES_FILE, "anomaly_votes")
    news_data = load_today_json(NEWS_SIGNALS_FILE, "news_signals_filtered")
    categories_data = load_json(CATEGORIES_FILE)

    rows, missing = build_rows_from_price_cache(price_cache, validation_report)
    if not rows and cloud_pc_data:
        rows = build_rows_from_cloud_pc(cloud_pc_data)
    display_rows, display_policy = select_daily_display_rows(rows, categories_data)

    history = {}
    try:
        history = build_all_products_history()
    except Exception as exc:
        print(f"[warn] history build failed: {exc}", file=sys.stderr)
        log_event("daily_payload.history_failed", ok=False, error=str(exc))

    history_products = history.get("products", {})
    for row in display_rows:
        pid = row.get("product_id")
        h = history_products.get(pid)
        if h and h.get("weekly"):
            pct = h["weekly"]["change_pct"]
            trend = h["weekly"]["trend"]
            if pct is not None:
                if abs(pct) < 0.5:
                    row["trend_label"] = "周持平"
                elif pct > 0:
                    row["trend_label"] = f"周涨{abs(pct):.1f}%"
                else:
                    row["trend_label"] = f"周跌{abs(pct):.1f}%"
            else:
                row["trend_label"] = None
            row["trend_direction"] = trend
            row["weekly_change_pct"] = pct
            row["monthly_change_pct"] = h["monthly"]["change_pct"] if h.get("monthly") else None
        else:
            row["trend_label"] = None
            row["trend_direction"] = None
            row["weekly_change_pct"] = None
            row["monthly_change_pct"] = None

    signals = normalize_signals(cloud_pc_data)
    signals = merge_news_signals(signals, news_data)
    signals = merge_anomaly_votes(signals, anomaly_votes)
    recommendations = cloud_pc_data.get("recommendations") or []
    if recommendations and not signals["A"] and not signals["S"]:
        signals["B"].extend({
            "title": rec,
            "source": "cloud_pc_daily_recommendation",
        } for rec in recommendations[:5])

    # 构建drop_alerts，添加baseline_date信息
    drop_alerts = []
    for alert in validation_report.get("warnings", []):
        if isinstance(alert, dict):
            # 尝试从price_cache获取baseline_date
            model_name = alert.get("model") or alert.get("product_name") or alert.get("product_id")
            if model_name and model_name in price_cache.get("models", {}):
                model_data = price_cache["models"][model_name]
                alert = alert.copy()
                alert["baseline_date"] = model_data.get("baseline_date") or "历史数据"
                alert["baseline_price"] = model_data.get("baseline_price")
        drop_alerts.append(alert)
    
    # 生成动作建议 (action_items)
    action_items = []
    try:
        engine = ActionEngine()
        # 构建扩展的payload信息用于action_engine
        extended_payload = {
            "signals": signals,
            "news_signals": news_data,
            "prices": rows,
        }
        action_items = engine.generate_actions_from_payload(extended_payload)
        # 转换为可序列化的dict列表
        action_items = [action.to_dict() for action in action_items]
        engine.save_actions(action_items)
    except Exception as exc:
        print(f"[warn] action engine failed: {exc}", file=sys.stderr)
        log_event("daily_payload.action_engine_failed", ok=False, error=str(exc))
    
    payload = {
        "version": "2.8.0",
        "date": today_str(),
        "generated_at": now_iso(),
        "summary": summarize(rows, signals, missing, cloud_pc_data, news_data),
        "signals": signals,
        "action_items": action_items,
        "prices": {
            "updated_at": price_cache.get("updated_at") or cloud_pc_data.get("generated_at"),
            "rows": display_rows,
            "all_rows_count": len(rows),
            "display_policy": display_policy,
            "daily_record": str(latest_daily_price_file()) if latest_daily_price_file() else None,
        },
        "history": history,
        "risks": {
            "drop_alerts": drop_alerts,
            "rise_alerts": [],
            "missing_data": missing,
            "validation_errors": validation_report.get("errors", []),
            "manual_confirmation_required": validation_report.get("manual_confirmation_required", False),
        },
        "images": {
            "market_daily_card": None,
            "price_monitor_card": None,
        },
        "sources": {
            "price_cache": str(PRICE_CACHE_FILE),
            "cloud_pc_daily": str(CLOUD_PC_DAILY_FILE) if cloud_pc_data else None,
            "validation_report": str(VALIDATION_REPORT_FILE) if validation_report else None,
            "anomaly_votes": str(ANOMALY_VOTES_FILE) if anomaly_votes else None,
            "news_signals_filtered": str(NEWS_SIGNALS_FILE) if news_data else None,
        },
    }

    output = Path(args.output)
    save_json(output, payload)
    if output.resolve() == PAYLOAD_FILE.resolve():
        update_push_status(payload)

    print(json.dumps({
        "ok": True,
        "output": str(output),
        "date": payload["date"],
        "rows": len(rows),
        "display_rows": len(display_rows),
        "display_policy": display_policy.get("mode"),
        "signals": {k: len(v) for k, v in signals.items()},
        "action_items_count": len(action_items),
        "missing": len(missing),
    }, ensure_ascii=False, indent=2))
    log_event(
        "daily_payload.done",
        ok=True,
        output=str(output),
        date=payload["date"],
        rows=len(rows),
        display_rows=len(display_rows),
        display_policy=display_policy.get("mode"),
        signals={k: len(v) for k, v in signals.items()},
        action_items_count=len(action_items),
        missing=len(missing),
    )


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        log_exception("daily_payload.exception", exc)
        raise
