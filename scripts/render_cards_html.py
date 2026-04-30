#!/usr/bin/env python3
"""
HTML+CSS 卡片渲染脚本 v2.5
将 daily_report_payload.json 数据渲染为 HTML 卡片并截图生成 PNG
支持6品类×2机型分组展示
"""
import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path

# 尝试导入 playwright
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

# 尝试导入 selenium
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False


BASE_DIR = Path(__file__).resolve().parent.parent
PAYLOAD_FILE = BASE_DIR / "data" / "daily_report_payload.json"
TEMPLATE_FILE = BASE_DIR / "templates" / "price_card.html"
OUTPUT_DIR = BASE_DIR / "data" / "report_cards"
CATEGORIES_FILE = BASE_DIR / "config" / "categories.json"

# 品牌词列表，用于去除机型名前缀
BRAND_PREFIXES = ["微星", "华硕", "技嘉", "七彩虹", "影驰", "索泰", "映众", "耕升", "铭瑄", "昂达", "金士顿"]

# 品类顺序和配置
CATEGORY_ORDER = [
    ("运动相机", "📷"),
    ("显卡", "🖥️"),
    ("CPU", "⚙️"),
    ("无人机", "🚁"),
    ("内存固态", "💾"),
    ("智能手环", "⌚"),
]

# 品类中核心机型优先级（每个品类指定1个核心机型，必须展示）
CORE_MODELS = {
    "运动相机": "DJI Pocket 3",
    "显卡": "RTX 4070",
    "CPU": "i5 13600K",
    "无人机": "DJI Mini 4",
    "内存固态": "DDR5 16G",
    "智能手环": "小米手环 10",
}


def load_json(path):
    """加载 JSON 文件"""
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_template(path):
    """加载 HTML 模板"""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def strip_brand_prefix(model_name):
    """去除机型名中的品牌前缀"""
    if not model_name:
        return ""
    for brand in BRAND_PREFIXES:
        if model_name.startswith(brand):
            # 去掉品牌词和后面的空格/分隔符
            return model_name[len(brand):].lstrip(" -_")
    return model_name


def is_night_mode(rows):
    """判断是否为晚间模式：检查 xianyu_recycle 和 aihuishou 是否有有效数据"""
    for row in rows:
        xr = row.get("xianyu_recycle", "—")
        ah = row.get("aihuishou", "—")
        if xr != "—" or ah != "—":
            return True
    return False


def format_change_class(change_str):
    """根据日环比返回 CSS 类名"""
    if not change_str or change_str == "—" or change_str == "0%":
        return "change-flat"
    if change_str.startswith("+") or change_str.startswith("↑"):
        return "change-up"
    if change_str.startswith("-") or change_str.startswith("↓"):
        return "change-down"
    return "change-flat"


def format_baseline_date(date_str):
    """格式化基准日期显示"""
    if not date_str or date_str == "历史数据":
        return "历史数据"
    return f"基准：{date_str}"


def format_time_display(time_str):
    """格式化时间显示，去掉秒数"""
    if not time_str:
        return ""
    # 格式: "2026-04-29 19:36:26" -> "4月29日 19:36"
    try:
        dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
        return f"{dt.month}月{dt.day}日 {dt.hour:02d}:{dt.minute:02d}"
    except ValueError:
        return time_str


def dedupe_signals(signals, max_count=5):
    """信号去重：按 title+source 去重，保留最新一条"""
    seen = {}
    for sig in signals:
        key = (sig.get("title", ""), sig.get("source", ""))
        if key not in seen:
            seen[key] = sig
    result = list(seen.values())
    # 按 published_at 降序排序
    result.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return result[:max_count]


def parse_change_percent(change_str):
    """解析日环比百分比，返回数值用于排序"""
    if not change_str or change_str == "—" or change_str == "0%":
        return 0
    # 移除 + - % 符号
    try:
        num_str = change_str.replace("+", "").replace("%", "").strip()
        return abs(float(num_str))
    except (ValueError, TypeError):
        return 0


def get_model_display_name(model_name):
    """获取显示用的机型名，去掉品牌前缀"""
    # 先检查是否匹配核心机型
    for core in CORE_MODELS.values():
        if core in model_name:
            return strip_brand_prefix(model_name)
    # 对于运动相机/无人机，保持DJI前缀
    if model_name.startswith("DJI ") or model_name.startswith("insta360 "):
        return model_name
    return strip_brand_prefix(model_name)


def load_categories():
    """加载品类配置"""
    if CATEGORIES_FILE.exists():
        return load_json(CATEGORIES_FILE)
    return {"categories": {}}


def build_model_to_category_map(categories_data):
    """构建机型ID到品类名称的映射"""
    model_map = {}
    BRAND_WORDS = ["微星", "华硕", "技嘉", "七彩虹", "影驰", "索泰", "映众", "耕升", "铭瑄", "昂达", "金士顿", "DJI", "insta360", "AMD", "Intel"]
    
    for cat_name, cat_data in categories_data.get("categories", {}).items():
        for item in cat_data.get("items", []):
            # 基本映射
            model_map[item["id"]] = cat_name
            model_map[item["name"]] = cat_name
            
            # 去掉品牌前缀后的名称
            stripped = item["name"]
            for brand in BRAND_WORDS:
                if stripped.startswith(brand):
                    stripped = stripped[len(brand):].strip()
                    break
            
            # 存储各种可能的匹配形式
            model_map[stripped] = cat_name
            model_map[stripped.replace(" ", "")] = cat_name
            model_map[item["name"].replace(" ", "")] = cat_name
            
            # 对于微星RTX 3060 -> RTX 3060
            if "RTX" in stripped:
                model_map[stripped] = cat_name
    return model_map


def select_models_for_category(rows, category_name, core_model_name, model_map):
    """为品类选择2个机型"""
    # 筛选该品类的机型
    category_rows = []
    for row in rows:
        model = row.get("model", "")
        product_id = row.get("product_id", "")
        
        # 检查是否属于该品类 - 多种匹配方式
        matched = False
        for check_val in [model, product_id, model.replace(" ", ""), model.replace("微星 ", "")]:
            if check_val in model_map and model_map[check_val] == category_name:
                matched = True
                break
        
        if matched:
            # 检查是否有价格数据
            has_price = row.get("xianyu_market") not in (None, "", "—")
            row_copy = row.copy()
            row_copy["_has_price"] = has_price
            category_rows.append(row_copy)
    
    if not category_rows:
        return []
    
    # 逻辑1：如果只有2个或更少，标记核心机型并返回
    if len(category_rows) <= 2:
        for row in category_rows:
            model = row.get("model", "")
            if core_model_name in model:
                row["_is_core"] = True
        # 确保核心机型在第一位
        category_rows.sort(key=lambda x: (0 if x.get("_is_core") else 1))
        return category_rows
    
    # 逻辑2：分离核心机型和非核心机型
    selected = []
    remaining = []
    
    for row in category_rows:
        model = row.get("model", "")
        if core_model_name in model:
            row["_is_core"] = True
            selected.append(row)
        else:
            remaining.append(row)
    
    # 逻辑3：如果已有2个选择（包含多个同名核心机型），去重
    if len(selected) >= 2:
        seen_models = set()
        unique_selected = []
        for row in selected:
            model = row.get("model", "")
            if model not in seen_models:
                seen_models.add(model)
                unique_selected.append(row)
        return unique_selected[:2]
    
    # 逻辑4：选日环比绝对值最大的作为第二个
    if remaining:
        remaining.sort(key=lambda x: parse_change_percent(x.get("daily_change", "")), reverse=True)
        # 去重
        seen_models = set(r.get("model", "") for r in selected)
        for r in remaining:
            model = r.get("model", "")
            if model not in seen_models:
                selected.append(r)
                seen_models.add(model)
                break
    
    # 确保核心机型在第一位
    selected.sort(key=lambda x: (0 if x.get("_is_core") else 1))
    
    return selected[:2]


def generate_category_table_header(is_night):
    """生成品类表格头部"""
    if is_night:
        return """<tr>
            <th style="width:30%">机型</th>
            <th style="width:22%">原均价</th>
            <th style="width:18%">最新价</th>
            <th style="width:15%">日环比</th>
            <th style="width:15%">回收价</th>
        </tr>"""
    else:
        return """<tr>
            <th style="width:35%">机型</th>
            <th style="width:25%">原均价</th>
            <th style="width:20%">最新价</th>
            <th style="width:20%">日环比</th>
        </tr>"""


def generate_category_table_rows(rows, is_night):
    """生成品类表格行"""
    if not rows:
        return '<tr class="empty-row"><td colspan="4">暂无数据</td></tr>'
    
    html_parts = []
    for row in rows:
        model = row.get("model", "—")
        display_name = get_model_display_name(model)
        baseline_price = row.get("baseline_price", "—")
        baseline_date = format_baseline_date(row.get("baseline_date", ""))
        xianyu_market = row.get("xianyu_market", "—")
        xianyu_recycle = row.get("xianyu_recycle", "—")
        daily_change = row.get("daily_change", "—")
        change_class = format_change_class(daily_change)
        is_core = row.get("_is_core")
        
        # 机型标签
        tag_html = ""
        if is_core:
            tag_html = '<span class="model-tag model-tag-core">核心</span>'
        elif parse_change_percent(daily_change) >= 5:
            tag_html = '<span class="model-tag model-tag-hot">异动</span>'
        
        if is_night:
            row_html = f"""<tr>
                <td>
                    <div class="model-name">{display_name}{tag_html}</div>
                    <div class="baseline">{baseline_date}</div>
                </td>
                <td class="price">{baseline_price}</td>
                <td class="price">{xianyu_market}</td>
                <td class="{change_class}">{daily_change}</td>
                <td class="price">{xianyu_recycle}</td>
            </tr>"""
        else:
            row_html = f"""<tr>
                <td>
                    <div class="model-name">{display_name}{tag_html}</div>
                    <div class="baseline">{baseline_date}</div>
                </td>
                <td class="price">{baseline_price}</td>
                <td class="price">{xianyu_market}</td>
                <td class="{change_class}">{daily_change}</td>
            </tr>"""
        html_parts.append(row_html)
    return "\n".join(html_parts)


def generate_category_group(category_name, emoji, rows, is_night):
    """生成单个品类分组HTML"""
    header_html = f"""<div class="category-header">
        <span class="category-name">{emoji} {category_name}</span>
        <span class="category-count">{len([r for r in rows if r.get('_has_price')])}/{len(rows)} 有价</span>
    </div>"""
    
    table_header = generate_category_table_header(is_night)
    table_rows = generate_category_table_rows(rows, is_night)
    
    table_html = f"""<table class="category-table">
        <thead>{table_header}</thead>
        <tbody>{table_rows}</tbody>
    </table>"""
    
    return f"""<div class="category-group">
    {header_html}
    {table_html}
    </div>"""


def generate_category_groups(rows, is_night):
    """生成所有品类分组"""
    categories_data = load_categories()
    model_map = build_model_to_category_map(categories_data)
    
    groups_html = []
    for category_name, emoji in CATEGORY_ORDER:
        core_model = CORE_MODELS.get(category_name, "")
        selected_rows = select_models_for_category(rows, category_name, core_model, model_map)
        
        # 为每个选中机型判断是否有价格
        for row in selected_rows:
            row["_has_price"] = row.get("xianyu_market") not in (None, "", "—")
            model = row.get("model", "")
            if core_model in model:
                row["_is_core"] = True
        
        group_html = generate_category_group(category_name, emoji, selected_rows, is_night)
        groups_html.append(group_html)
    
    return "\n".join(groups_html)


def clean_signal_title(title):
    """清理信号标题，去除平台前缀"""
    prefixes = ["douyin signal: ", "bilibili signal: ", "xiaohongshu signal: "]
    for prefix in prefixes:
        if title.startswith(prefix):
            return title[len(prefix):]
    return title


def generate_signal_box(level, signals):
    """生成信号框 HTML"""
    if not signals:
        return ""
    
    level_config = {
        "S": {"class": "signal-s", "label": "S级 紧急信号", "dot": "🔴"},
        "A": {"class": "signal-a", "label": "A级 重要信号", "dot": "🟡"},
        "B": {"class": "signal-b", "label": "B级 一般信号", "dot": "🔵"},
    }
    config = level_config.get(level, level_config["B"])
    
    items_html = []
    for sig in signals[:5]:  # 最多5条
        title = clean_signal_title(sig.get("title", "无标题"))
        source = sig.get("source", "未知来源")
        time_str = format_time_display(sig.get("published_at", ""))
        
        if level in ["S", "A"]:
            meta = f"{source} · {time_str}"
        else:
            meta = source
        
        items_html.append(f"""<div class="signal-item">
            <div class="signal-item-title">{title}</div>
            <div class="signal-item-meta">{meta}</div>
        </div>""")
    
    return f"""<div class="signal-box {config['class']}">
        <div class="signal-label">{config['dot']} {config['label']}</div>
        {"".join(items_html)}
    </div>"""


def render_html(payload, template_html):
    """渲染 HTML 模板"""
    prices = payload.get("prices", {})
    rows = prices.get("rows", [])
    signals = payload.get("signals", {})
    summary = payload.get("summary", {})
    
    date = payload.get("date", datetime.now().strftime("%Y年%m月%d日"))
    if "/" in date:
        # 转换 2026-04-30 -> 2026年04月30日
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            date = f"{dt.year}年{dt.month}月{dt.day}日"
        except ValueError:
            pass
    updated_at = payload.get("generated_at", "")[:16] if payload.get("generated_at") else ""
    if updated_at:
        try:
            dt = datetime.strptime(updated_at, "%Y-%m-%dT%H:%M:%S")
            updated_at = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass
    
    # 判断模式
    night_mode = is_night_mode(rows)
    mode_label = "📊 晚间详细行情" if night_mode else "☀️ 白天行情播报"
    
    # 生成品类分组
    category_groups_html = generate_category_groups(rows, night_mode)
    
    # 生成信号
    s_signals = signals.get("S", [])
    a_signals = dedupe_signals(signals.get("A", []))
    b_signals = dedupe_signals(signals.get("B", []))
    
    s_html = generate_signal_box("S", s_signals) if s_signals else ""
    a_html = generate_signal_box("A", a_signals)
    b_html = generate_signal_box("B", b_signals)
    
    # 替换占位符
    html = template_html
    replacements = {
        "{{date}}": date,
        "{{updated_at}}": updated_at,
        "{{mode_label}}": mode_label,
        "{{category_groups}}": category_groups_html,
        "{{s_signals}}": s_html,
        "{{a_signals}}": a_html,
        "{{b_signals}}": b_html,
        "{{data_quality}}": summary.get("data_quality", ""),
    }
    
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)
    
    return html


def html_to_png_playwright(html_path, png_path, width=1080, height=1920):
    """使用 Playwright 将 HTML 转换为 PNG"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(f"file://{html_path}")
        # 等待字体加载
        page.wait_for_timeout(500)
        page.screenshot(path=png_path, full_page=True)
        browser.close()
    return True


def html_to_png_selenium(html_path, png_path, width=1080, height=1920):
    """使用 Selenium 将 HTML 转换为 PNG"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument(f"--window-size={width},{height}")
    options.add_argument("--screenshot=" + png_path)
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(options=options)
    driver.get(f"file://{html_path}")
    import time
    time.sleep(1)  # 等待渲染
    driver.save_screenshot(png_path)
    driver.quit()
    return True


def html_to_png(html_path, png_path, width=1080, height=1920):
    """将 HTML 转换为 PNG，优先使用 Playwright"""
    if PLAYWRIGHT_AVAILABLE:
        print("使用 Playwright 截图...")
        try:
            return html_to_png_playwright(html_path, png_path, width, height)
        except Exception as e:
            print(f"Playwright 截图失败: {e}")
    
    if SELENIUM_AVAILABLE:
        print("使用 Selenium 截图...")
        try:
            return html_to_png_selenium(html_path, png_path, width, height)
        except Exception as e:
            print(f"Selenium 截图失败: {e}")
    
    print("警告: Playwright 和 Selenium 都不可用，无法自动截图")
    print("请手动打开 HTML 文件并截图")
    return False


def main():
    parser = argparse.ArgumentParser(description="HTML+CSS 卡片渲染脚本 v2.5")
    parser.add_argument("--payload", type=str, help="payload 文件路径")
    parser.add_argument("--template", type=str, help="HTML 模板路径")
    parser.add_argument("--output", type=str, help="输出目录")
    parser.add_argument("--no-screenshot", action="store_true", help="只生成 HTML，不截图")
    args = parser.parse_args()
    
    payload_file = Path(args.payload) if args.payload else PAYLOAD_FILE
    template_file = Path(args.template) if args.template else TEMPLATE_FILE
    output_dir = Path(args.output) if args.output else OUTPUT_DIR
    
    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 加载数据
    print(f"加载数据: {payload_file}")
    payload = load_json(payload_file)
    
    print(f"加载模板: {template_file}")
    template_html = load_template(template_file)
    
    # 渲染 HTML
    print("渲染 HTML (v2.5 品类分组)...")
    html_content = render_html(payload, template_html)
    
    # 保存 HTML 文件
    html_path = output_dir / "report_cards_combined.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"HTML 已保存: {html_path}")
    
    # 截图
    if not args.no_screenshot:
        png_path = output_dir / "report_cards_combined.png"
        print(f"开始截图...")
        if html_to_png(str(html_path), str(png_path)):
            print(f"PNG 已保存: {png_path}")
        else:
            print("截图失败")


if __name__ == "__main__":
    main()
