# 运动相机追踪系统 - 文件导出包

## 目录结构

```
运动相机追踪_导出包/
├── config/                    # 配置文件
│   ├── categories.json        # 品类配置（v3.0.0）
│   ├── thresholds.json        # 异动阈值配置
│   ├── baseline.json          # 价格基准线
│   └── brand_tiers.json       # 品牌层级
│
├── scripts/                   # 核心脚本
│   ├── price_crawler.py       # 三价格爬取
│   ├── price_archiver.py      # 价格归档
│   ├── price_history_analyzer.py  # 历史分析
│   ├── signal_freshness.py    # 信号时效性
│   ├── watchdog.py            # 任务看门狗
│   ├── alerting.py            # 告警推送
│   ├── volume_price_judge.py  # 量价判断
│   └── safe_storage.py        # 安全存储
│
├── cloud-pc-monitor/          # 云电脑监控模块
│   ├── config/
│   │   ├── models.json        # 监控机型配置
│   │   ├── thresholds.json    # 阈值配置
│   │   └── quota.json         # 配额配置
│   └── scripts/
│       ├── analyze.py         # 5算法投票分析
│       ├── threshold.py       # 阈值自适应
│       ├── output_for_daily.py # 日报输出
│       └── price_archiver.py  # 归档脚本
│
├── docs/                      # 技术文档
│   ├── SKILL_技术规范_v2.5.md  # ⭐ 核心技术规范
│   ├── 系统设计方案_v1.0.md
│   ├── 日程改造清单.md
│   ├── 新品发布回收量预测方法论.md
│   ├── 价格历史归档设计方案.md
│   └── ...
│
├── templates/                 # 模板文件
│   ├── daily_report_card.md
│   └── 双卡片模板.md
│
├── 记忆文件/                  # 系统记忆
│   ├── MEMORY.md              # 系统记忆
│   ├── SOUL.md                # 角色设定
│   ├── TOOLS.md               # 工具经验
│   ├── USER.md                # 用户画像
│   └── SECRET.md              # 密钥信息
│
├── 提示词_价格数据汇总.md
├── 提示词_信号分级判断.md
├── 提示词_推送格式.md
├── 整合方案文档.md
├── 工作流节点图.md
└── 当前任务流程.md
```

## 核心问题记录（2026-04-28）

### 统一口径
- 最高优先级运行规范：`docs/系统运行总规范_20260428.md`
- 唯一调度配置：`config/schedule.json`
- 正式日报播报时间：每日 **10:00**
- 06:00 只用于生成日报数据和图片，不作为正式播报时间
- 日报/周报/月报必须以图片卡片发送，禁止发送完整 Markdown 日报

### 当前可执行日报链路
```bash
python3 scripts/init_daily_status.py
python3 scripts/generate_daily_report_payload.py
python3 scripts/render_report_cards.py
python3 scripts/report_guard.py before_push
python3 scripts/send_daily_report.py --dry-run
```

### 实际运行模块
原架构的三条业务线保留，不删除：

1. 市场追踪日报：06:00 生成日报数据和图片，10:00 正式推送
2. 白天异动检测：07:30、12:00、17:30 执行 A层8个机型轻量检测
3. 晚间全量检测：21:00 执行 A+B层22个机型深度爬取
4. 云电脑扫描：每 2 小时执行一次轻量价格扫描，输出到日报

目录里脚本较多，但日常不是全部运行。按职责分为 7 个支撑模块：

1. 配置规则：`config/*.json`、`config/thresholds_v2.py`
2. 价格抓取：`scripts/price_crawler.py`
3. 价格归档与历史分析：`scripts/price_archiver.py`、`scripts/price_history_analyzer.py`
4. 量价与信号判断：`scripts/volume_price_judge.py`、`scripts/confidence_calculator.py`、`scripts/signal_freshness.py`
5. 日报生成与图片渲染：`scripts/init_daily_status.py`、`scripts/generate_daily_report_payload.py`、`scripts/render_report_cards.py`
6. 推送与守护：`scripts/report_guard.py`、`scripts/send_daily_report.py`、`scripts/alerting.py`、`scripts/watchdog.py`
7. 云电脑监控与基准维护：`cloud-pc-monitor/scripts/*.py`、`scripts/run_cloud_pc_scan.py`、`scripts/update_baseline.py`

### 白天异动检测链路
外部日程只在 07:30、12:00、17:30 调用白天异动检测：
```bash
python3 scripts/run_daytime_scan.py run --slot HH:MM
```

只刷新 payload 和图片、不执行网络爬取时：
```bash
python3 scripts/run_daytime_scan.py run --slot HH:MM --no-crawl
```

### 日间增量巡检
10:00、14:00、18:00 是轻量资讯巡检口径，不是完整价格扫描。10:00 首先执行正式日报推送，推送完成后才允许做轻量补充巡检。

### 晚间全量检测链路
外部日程在 21:00 调用：
```bash
python3 scripts/run_daytime_scan.py run --slot 21:00
```

晚间全量检测覆盖 A+B 层22个机型，结果进入 `data/anomaly_votes.json`、`data/daily_report_payload.json` 和图片卡片。

### 云电脑每2小时扫描链路
外部日程在 08:00、10:00、12:00、14:00、16:00、18:00、20:00、22:00 调用：
```bash
python3 scripts/run_cloud_pc_scan.py run --slot HH:MM
```

云电脑扫描输出 `cloud_pc_daily.json`，再并入 `data/daily_report_payload.json`。

### 数据验证与基准更新
每次价格扫描后会执行：
```bash
python3 scripts/price_data_validator.py
python3 scripts/price_daily_recorder.py
```

资讯进入日报前会执行：
```bash
python3 scripts/news_signal_filter.py
```

每周基准更新先生成待确认方案，不直接覆盖：
```bash
python3 scripts/update_baseline.py
```

实际推送前需配置环境变量：
```bash
export WECOM_WEBHOOK_URL="企业微信机器人Webhook"
export REPORT_CARD_BASE_URL="可公开访问data/report_cards的URL，可选"
```

安全要求：
- `记忆文件/SECRET.md` 只允许本地保存，已加入 `.gitignore` / `.exportignore`
- 对外打包时必须排除 `SECRET.md`

### 问题1：凌晨3:30推送
- 根因：云电脑扫描日程 HOURLY+interval=2 全天候执行
- 修复：扫描限制在 `config/schedule.json` 的白天窗口内，静默期 22:30-07:30 禁止普通推送

### 问题2：10点没有推送
- 根因：推送状态未持久化，且 06:00/10:00 规则冲突
- 修复：10:00 设为唯一正式播报时间；推送前检查 `data/push_status.json`；失败按 10:10/10:20/10:30 重试

### 问题3：推送格式不对
- 规范要求：日报必须用图片卡片形式
- 修复：`提示词_推送格式.md` 已禁止完整 Markdown 日报；图片失败时只允许发送失败通知

### 问题4：日报链路不闭环
- 根因：缺少 payload 生成、图片生成、推送闸门、实际发送入口
- 修复：新增 `init_daily_status.py`、`generate_daily_report_payload.py`、`render_report_cards.py`、`report_guard.py`、`send_daily_report.py`

## Opus优化方案

1. 扫描加时间窗口（08:00-22:00）
2. 日报加重试和watchdog
3. 告警加静默期（22:30-07:30）和分级推送
