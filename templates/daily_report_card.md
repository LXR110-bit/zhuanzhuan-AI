# 价格追踪日报卡片 - 生图模板

## 布局结构

```
┌─────────────────────────────┐
│  ① 标题区 (~10%)            │  深色背景，白色标题 + 日期
├─────────────────────────────┤
│  ② 核心指标区 (~12%)        │  3个卡片：均价/机型数/异动数
├─────────────────────────────┤
│  ③ 价格对比区 (~40%)        │  表格：机型 | 闲鱼自由市场 | 闲鱼官方回收 | 爱回收 | 日环比
├─────────────────────────────┤
│  ④ 异动列表区 (~28%)        │  红/绿高亮卡片，涨跌幅
├─────────────────────────────┤
│  ⑤ 底部信息区 (~10%)        │  数据来源/更新时间
└─────────────────────────────┘
```

## 生图Prompt模板

```
A vertical mobile infographic card (1080×1920px, 9:16 aspect ratio) for a
daily second-hand price tracking report. Clean, modern, data-dashboard
style with a dark navy-to-deep-blue gradient background. Chinese text throughout.

-- SECTION 1: HEADER (top 10%) --
Large bold white title "价格追踪日报" centered, with the date "{DATE}"
in a smaller light-blue tag beneath it.

-- SECTION 2: KEY METRICS (next 12%) --
Three rounded-corner metric cards in a horizontal row:
  • Left: "¥{AVG_PRICE}" labeled "市场均价" with {CHANGE_COLOR} arrow
  • Center: "{MODEL_COUNT}" labeled "监控机型"
  • Right: "{ALERT_COUNT}" labeled "今日异动" with orange indicator

-- SECTION 3: PRICE COMPARISON TABLE (next 40%) --
A clean table with alternating row shading.
Column headers: "机型 | 闲鱼自由市场 | 闲鱼官方回收 | 爱回收 | 日环比"
{TABLE_ROWS}

-- SECTION 4: ANOMALY ALERT LIST (next 28%) --
Section titled "⚠️ 今日异动机型" in bold orange-yellow text.
{ALERT_CARDS}

-- SECTION 5: FOOTER (bottom 10%) --
Small light-gray text:
  "数据来源：闲鱼自由市场 · 闲鱼官方回收 · 爱回收 | 更新时间：{TIME}"

-- STYLE KEYWORDS --
UI design, mobile dashboard, data visualization, infographic, clean layout,
professional, fintech style, high contrast, 4K quality
```

## 使用方法

1. 替换 `{DATE}`, `{AVG_PRICE}` 等变量为实际数据
2. 调用 `image_generate` 工具生成图片
3. 图片保存到 `imgs/daily_report/` 目录

## 防丢失机制

此模板文件位置：`./运动相机追踪/templates/daily_report_card.md`
- 独立文件，不与其他逻辑耦合
- 每次生成日报时读取此模板
- 如有修改需同步更新此处
