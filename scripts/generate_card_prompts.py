#!/usr/bin/env python3
"""
Generate AI image prompts from daily report payload for card generation.

This script reads daily_report_payload.json and price_cache.json,
then generates three card prompts:
1. Price Card (price_card) - price table
2. Signal Card (signal_card) - S/A level market signals  
3. Summary Card (summary_card) - daily summary and action

Usage:
    python generate_card_prompts.py
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

# Base directory setup
BASE_DIR = Path(__file__).resolve().parent.parent
PAYLOAD_FILE = BASE_DIR / "data" / "daily_report_payload.json"
PRICE_CACHE_FILE = BASE_DIR / "data" / "price_cache.json"
TEMPLATE_FILE = BASE_DIR / "config" / "card_prompt_templates.json"
OUTPUT_FILE = BASE_DIR / "data" / "card_prompts.json"

# Brand prefixes to remove from model names
BRAND_PREFIXES = ["微星", "华硕", "技嘉", "七彩虹", "影驰"]


def load_json(path: Path) -> dict:
    """Load JSON file."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Save JSON file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def clean_model_name(name: str) -> str:
    """Remove brand prefix from model name."""
    for prefix in BRAND_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):].strip()
    return name


def format_date_friendly(iso_str: str) -> str:
    """Convert ISO date string to friendly format like '4月30日'."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return f"{dt.month}月{dt.day}日"
    except (ValueError, AttributeError):
        return iso_str


def format_time_friendly(iso_str: str) -> str:
    """Convert ISO datetime to friendly format like '4月30日 09:34'."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return f"{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}"
    except (ValueError, AttributeError):
        return iso_str


def deduplicate_signals(signals: list[dict]) -> list[dict]:
    """Deduplicate signals by title + source combination."""
    seen = set()
    result = []
    for sig in signals:
        key = (sig.get("title", ""), sig.get("source", ""))
        if key not in seen:
            seen.add(key)
            result.append(sig)
    return result


def build_price_card_prompt(payload: dict, price_cache: dict, template: dict) -> str:
    """Build price card prompt."""
    date_str = payload.get("date", "")
    date_display = format_date_friendly(date_str)
    
    # Get price table from payload, fallback to price_cache
    price_table = payload.get("price_table", [])
    
    # If price_table is empty, generate from price_cache
    if not price_table and price_cache.get("models"):
        for model_name, model_data in price_cache["models"].items():
            sources = model_data.get("sources", [])
            xianyu_market = None
            aihuishou = None
            latest_price = None
            
            for src in sources:
                platform = src.get("platform", "")
                price_val = src.get("price", "")
                
                if "闲鱼" in platform and "回收" not in platform:
                    xianyu_market = price_val
                elif "爱回收" in platform:
                    aihuishou = price_val
                
                # Use first available price as latest
                if not latest_price and price_val:
                    latest_price = price_val
            
            price_table.append({
                "model": model_name,
                "baseline_price": model_data.get("baseline_price", latest_price or "-"),
                "xianyu_market": xianyu_market,
                "xianyu_official": None,
                "aihuishou": aihuishou,
                "latest_price": latest_price,
                "change_1d": model_data.get("change_percent")
            })
    
    # Determine if we have multi-platform data
    has_multi_platform = any(
        row.get("xianyu_market") or row.get("aihuishou") or row.get("xianyu_official")
        for row in price_table
    )
    
    # Get column headers
    if has_multi_platform:
        col_headers = "Model | Xianyu Market | Xianyu Recycle | AiHuiShou | Change"
        col_headers_cn = "机型 | 闲鱼市场 | 闲鱼回收 | 爱回收 | 涨跌"
    else:
        col_headers = "Model | Baseline | Latest | Change"
        col_headers_cn = "机型 | 原均价 | 最新价 | 涨跌"
    
    # Build model rows
    model_rows = []
    for row in price_table[:8]:  # Max 8 rows for readability
        model = clean_model_name(row.get("model", ""))
        baseline = row.get("baseline_price", "-")
        latest = row.get("xianyu_market") or row.get("latest_price") or baseline
        change = row.get("change_1d") or row.get("change_percent") or "0%"
        
        # Determine color indicator
        if change.startswith("+"):
            change_display = f"[GREEN]+{change[1:]}%[/]"
        elif change.startswith("-"):
            change_display = f"[RED]{change}%"
        else:
            change_display = f"[GRAY]{change}"
        
        if has_multi_platform:
            xianyu = row.get("xianyu_market") or "-"
            recycle = row.get("xianyu_recycle") or "-"
            aihui = row.get("aihuishou") or "-"
            row_str = f"{model} | {xianyu} | {recycle} | {aihui} | {change_display}"
        else:
            row_str = f"{model} | {baseline} | {latest} | {change_display}"
        
        model_rows.append(row_str)
    
    row_count = len(model_rows)
    update_time = format_time_friendly(payload.get("generated_at", ""))
    data_source = price_cache.get("source", "Price Monitor System")
    
    # Build prompt
    prompt = f"""Price Monitor Report Card - {date_display}

[STYLE] Dark fintech dashboard theme, 1080x1920 portrait mobile card. Navy gradient background (#1a1a2e to #16213e). Flat design, no shadows. Chinese language.

[LAYOUT]
- Top: Header banner with '价格监控' title, date '{date_display}', white text on dark card
- Center: Price comparison table with {row_count} rows
- Bottom: Data source '{data_source}' and update time '{update_time}'

[TABLE HEADERS]
{col_headers_cn}

[TABLE DATA - EXACT NUMBERS]
{chr(10).join(model_rows)}

[STYLE RULES]
- Model names: Clean product names like 'RTX 3060' (NO brand prefixes)
- Price format: Use exact prices like '1600-1900元' or '1432-1700元'
- Change %: Green (#00e676) for +X%, Red (#ff5252) for -X%, Gray for 0%
- Row alternating: #0f0f23 / #141428
- Numbers must be precise in monospace style
- Table columns must be perfectly aligned

[QUALITY]
- All numbers exact as specified, no approximations
- Chinese text clear and properly sized
- Professional financial data card appearance"""

    return prompt


def build_signal_card_prompt(payload: dict, template: dict) -> str:
    """Build signal card prompt."""
    date_str = payload.get("date", "")
    date_display = format_date_friendly(date_str)
    
    signals = payload.get("signals", {})
    s_signals = deduplicate_signals(signals.get("S", []))[:2]
    a_signals = deduplicate_signals(signals.get("A", []))[:3]
    b_signals = deduplicate_signals(signals.get("B", []))[:2]
    
    # Combine and limit
    all_signals = []
    for sig in s_signals:
        sig["level"] = "S"
        all_signals.append(sig)
    for sig in a_signals:
        sig["level"] = "A"
        all_signals.append(sig)
    for sig in b_signals:
        sig["level"] = "B"
        all_signals.append(sig)
    
    s_count = len(s_signals)
    a_count = len(a_signals)
    b_count = len(b_signals)
    signal_count = len(all_signals)
    
    # Build signal list
    signal_list = []
    for sig in all_signals:
        level = sig.get("level", "B")
        title = sig.get("title", "")
        source = sig.get("source", "")
        published = sig.get("published_at", "")
        time_display = format_date_friendly(published) if published else ""
        
        # Extract source name
        if "douyin" in source.lower():
            source_name = "抖音"
        elif "weibo" in source.lower():
            source_name = "微博"
        elif "xiaohongshu" in source.lower() or "redbook" in source.lower():
            source_name = "小红书"
        else:
            source_name = source.split(":")[-1] if ":" in source else source
        
        sig_str = f"[{level}] {source_name} | {title} | {time_display}"
        signal_list.append(sig_str)
    
    prompt = f"""Market Signals Alert Card - {date_display}

[STYLE] Dark news alert card, 1080x1920 portrait. Navy background (#1a1a2e). Flat design. Chinese language. Professional financial alert aesthetic.

[LAYOUT]
- Header: '市场信号速报' title with level counts (S:{s_count} A:{a_count} B:{b_count})
- Signal list with {signal_count} deduplicated signals
- Each signal: [LEVEL BADGE] [SOURCE] [TITLE] [TIME]

[SIGNAL DATA]
{chr(10).join(signal_list)}

[STYLE RULES]
- S-level badge: Gold (#ffd700) rounded rectangle
- A-level badge: Blue (#448aff) rounded rectangle  
- B-level badge: Gray (#94a3b8) rounded rectangle
- Source shown as platform name like '抖音' or '微博'
- Titles should be concise and readable
- Time format: '昨天' or date '4月29日'
- Background card for each signal with subtle border

[QUALITY]
- Signals deduplicated (same title+source = one entry)
- Display most recent signals first
- Chinese text clear and legible
- Clean professional alert card appearance"""

    return prompt


def build_summary_card_prompt(payload: dict, template: dict) -> str:
    """Build summary card prompt."""
    date_str = payload.get("date", "")
    date_display = format_date_friendly(date_str)
    
    summary = payload.get("summary", {})
    one_sentence = summary.get("one_sentence", "今日市场平稳")
    today_action = summary.get("today_action", "持续监控")
    data_quality = summary.get("data_quality", "数据正常")
    
    # Extract counts
    signals = payload.get("signals", {})
    s_count = len(signals.get("S", []))
    a_count = len(signals.get("A", []))
    b_count = len(signals.get("B", []))
    total_signals = s_count + a_count + b_count
    
    # Price count from payload or cache
    price_count = len(payload.get("price_table", []))
    if price_count == 0:
        price_count = len(payload.get("price_table", [])) or 8  # Default
    
    prompt = f"""Daily Market Summary Card - {date_display}

[STYLE] Dark executive summary card, 1080x1920 portrait. Navy gradient (#1a1a2e to #16213e). Flat design. Chinese language. Premium fintech dashboard aesthetic.

[LAYOUT]
- Top: Section label '今日摘要' in accent color
- Hero: Main summary text '{one_sentence}' in large white text
- Middle: Key metrics display
  - Card 1: {price_count} 价格项
  - Card 2: {total_signals} 关注信号 (S:{s_count} A:{a_count} B:{b_count})
  - Card 3: {data_quality}
- Bottom: Action section with '{today_action}' highlighted

[METRICS STYLING]
- Large numbers in accent blue (#448aff)
- Labels in muted gray (#94a3b8)
- Metric cards with subtle borders

[ACTION HIGHLIGHT]
- Use green accent (#00e676) or blue accent for action box
- Action text should be prominent and actionable
- Clear call-to-action appearance

[QUALITY]
- Chinese text must be clear and properly rendered
- Numbers exact as provided
- Professional executive dashboard style
- Clean visual hierarchy"""

    return prompt


def main():
    """Main function to generate card prompts."""
    print("Loading data files...")
    
    payload = load_json(PAYLOAD_FILE)
    price_cache = load_json(PRICE_CACHE_FILE)
    template = load_json(TEMPLATE_FILE)
    
    if not payload:
        print(f"Warning: {PAYLOAD_FILE} not found or empty")
    if not price_cache:
        print(f"Warning: {PRICE_CACHE_FILE} not found or empty")
    
    print("Building card prompts...")
    
    # Generate prompts
    price_card = build_price_card_prompt(payload, price_cache, template)
    signal_card = build_signal_card_prompt(payload, template)
    summary_card = build_summary_card_prompt(payload, template)
    
    # Build output
    output = {
        "version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "source_date": payload.get("date", ""),
        "cards": {
            "price_card": {
                "description": "价格播报卡 - 展示所有监控品类的价格表",
                "prompt": price_card,
                "card_type": "price_card"
            },
            "signal_card": {
                "description": "信号速报卡 - 展示S/A级市场信号",
                "prompt": signal_card,
                "card_type": "signal_card"
            },
            "summary_card": {
                "description": "摘要卡 - 今日一句话总结和行动建议",
                "prompt": summary_card,
                "card_type": "summary_card"
            }
        },
        "metadata": {
            "image_specs": template.get("image_specs"),
            "style_constants": template.get("style_constants")
        }
    }
    
    # Save output
    save_json(OUTPUT_FILE, output)
    print(f"Card prompts saved to: {OUTPUT_FILE}")
    
    # Print prompts for review
    print("\n" + "="*60)
    print("PRICE CARD PROMPT:")
    print("="*60)
    print(price_card[:2000])
    
    print("\n" + "="*60)
    print("SIGNAL CARD PROMPT:")
    print("="*60)
    print(signal_card[:2000])
    
    print("\n" + "="*60)
    print("SUMMARY CARD PROMPT:")
    print("="*60)
    print(summary_card[:2000])
    
    return output


if __name__ == "__main__":
    main()
