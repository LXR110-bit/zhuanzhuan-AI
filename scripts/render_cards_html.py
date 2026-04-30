#!/usr/bin/env python3
"""
HTML+CSS 卡片渲染脚本
将 daily_report_payload.json 数据渲染为 HTML 卡片并截图生成 PNG
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

# 品牌词列表，用于去除机型名前缀
BRAND_PREFIXES = ["微星", "华硕", "技嘉", "七彩虹", "影驰", "索泰", "映众", "耕升", "铭瑄", "昂达"]


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


def generate_table_header(is_night):
    """生成表格头部 HTML"""
    if is_night:
        return """<th>机型</th><th>闲鱼市场</th><th>闲鱼回收</th><th>爱回收</th><th>日环比</th>"""
    else:
        return """<th>机型</th><th>原均价(基准期)</th><th>最新价</th><th>日环比</th>"""


def generate_table_rows(rows, is_night):
    """生成表格行 HTML"""
    html_parts = []
    for row in rows:
        model = strip_brand_prefix(row.get("model", "—"))
        baseline_price = row.get("baseline_price", "—")
        baseline_date = format_baseline_date(row.get("baseline_date", ""))
        xianyu_market = row.get("xianyu_market", "—")
        xianyu_recycle = row.get("xianyu_recycle", "—")
        aihuishou = row.get("aihuishou", "—")
        daily_change = row.get("daily_change", "—")
        change_class = format_change_class(daily_change)
        
        if is_night:
            # 晚间模式：5列
            row_html = f"""<tr>
                <td>
                    <div class="model-name">{model}</div>
                    <div class="baseline">{baseline_date}</div>
                </td>
                <td class="price">{xianyu_market}</td>
                <td class="price">{xianyu_recycle}</td>
                <td class="price">{aihuishou}</td>
                <td class="{change_class}">{daily_change}</td>
            </tr>"""
        else:
            # 白天模式：4列
            row_html = f"""<tr>
                <td>
                    <div class="model-name">{model}</div>
                    <div class="baseline">{baseline_date}</div>
                </td>
                <td class="price">{baseline_price}</td>
                <td class="price">{xianyu_market}</td>
                <td class="{change_class}">{daily_change}</td>
            </tr>"""
        html_parts.append(row_html)
    return "\n".join(html_parts)


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
    
    # 生成表格
    table_header = generate_table_header(night_mode)
    table_rows = generate_table_rows(rows, night_mode)
    
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
        "{{table_header}}": table_header,
        "{{table_rows}}": table_rows,
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
    parser = argparse.ArgumentParser(description="HTML+CSS 卡片渲染脚本")
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
    print("渲染 HTML...")
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
            print("截图失败，请手动截图")
    
    print("\n完成!")
    print(f"输出文件: {html_path}")
    if not args.no_screenshot:
        print(f"PNG 文件: {output_dir / 'report_cards_combined.png'}")


if __name__ == "__main__":
    main()
