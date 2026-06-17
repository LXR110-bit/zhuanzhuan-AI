# Coze 3.0 行情双 Agent 日程模板

> 用于将原 `侦察兵小B_行情监控` 拆分为 `侦察兵小C_价格监控` 与 `侦察兵小B_信号监控`。日常循环只创建 4 条 MO-FR；机动任务只保留模板，不创建循环。

## 通用执行前置

所有日程 description 都必须包含：

```text
【生产执行器】云电脑 小MAC mini
【执行方式】使用 bash 工具，指定 desktop_name=cloud
【云端目录】/root/coze-production/zhuanzhuan-AI
【生产分支】local/dev
【Git 前置】
cd /root/coze-production/zhuanzhuan-AI
GIT_SSH_COMMAND="ssh -F /root/coze-production/.ssh/config" git fetch origin
git checkout local/dev
GIT_SSH_COMMAND="ssh -F /root/coze-production/.ssh/config" git pull --ff-only origin local/dev
git status --short --branch
git rev-parse --short HEAD
```

共同禁止项：不使用 `yinhemanyouzhinan.local`；不改代码/配置；不 commit/push 代码；不输出真实 webhook；不创建超出本模板的循环日程。

## 1. 06:00 早盘价格全量任务包

- Agent：`侦察兵小C_价格监控`
- 频率：MO-FR 06:00
- 输出渠道：扣子主对话；不推送飞书日报

允许执行：

```bash
python3 scripts/price_data_validator.py
python3 scripts/price_daily_recorder.py
python3 scripts/price_archiver.py archive
python3 scripts/generate_daily_report_payload.py
python3 scripts/render_cards_html.py
```

说明：完成主要采价后的校验、记录、归档、日报 payload 和卡片预渲染；如需 mobile_use 采价，必须限定在价格采集范围内。禁止调用 TikHub/search_web 做信号扩展。

## 2. 10:00 价格日报推送任务包

- Agent：`侦察兵小C_价格监控`
- 频率：MO-FR 10:00
- 输出渠道：扣子主对话 + 飞书群；企业微信仅作备用

允许执行：

```bash
python3 scripts/send_daily_report.py
```

说明：检查 06:00 产物并推送。若 06:00 产物缺失，允许脚本按既有兜底逻辑补生成；不得临时重采价。飞书标题必须以 `【价格监控】` 开头。

## 3. 08:30 早盘信号雷达

- Agent：`侦察兵小B_信号监控`
- 频率：MO-FR 08:30
- 输出渠道：扣子主对话；S/A 级推飞书；B 级只进日志/扣子

允许执行：

```bash
python3 scripts/multi_engine_search.py --profile platform_policy --dry-run
# 如已采集search_web结果：python3 scripts/multi_engine_search.py --profile platform_policy --input <search_results.json>
python3 scripts/fetch_tikhub_signals.py --append
python3 scripts/news_signal_filter.py
python3 scripts/send_signal_digest.py
```

说明：抓早间热点、新品、政策、平台变化，去重并分级；多引擎搜索只产出平台政策待验证候选线索和运营承接预备，禁止当作已确认政策。禁止 mobile_use、禁止写 `data/price_cache.json`。

## 4. 15:30 午后信号补扫

- Agent：`侦察兵小B_信号监控`
- 频率：MO-FR 15:30
- 输出渠道：扣子主对话；S/A 级推飞书；B 级只进日志/扣子

允许执行：

```bash
python3 scripts/multi_engine_search.py --profile platform_policy --dry-run
# 如已采集search_web结果：python3 scripts/multi_engine_search.py --profile platform_policy --input <search_results.json>
python3 scripts/fetch_tikhub_signals.py --append
python3 scripts/news_signal_filter.py
python3 scripts/send_signal_digest.py
```

说明：补抓午后热点，复查早盘失败源，避免一次失败导致全天空白；如有大促/国补/以旧换新线索，按平台政策证据闸门输出运营承接预备。禁止 mobile_use、禁止写 `data/price_cache.json`。

## 5. 18:00 晚盘价格机动任务包（不建循环）

- Agent：`侦察兵小C_价格监控`
- 类型：非循环单次事件 / 手动触发
- 使用场景：晚盘复查、官方回收价/爱回收补采、重大价格异动复核
- 禁止：常态 MO-FR 循环、TikHub/search_web 信号扩展

## 6. 20:30 晚间信号机动任务包（不建循环）

- Agent：`侦察兵小B_信号监控`
- 类型：非循环单次事件 / 手动触发
- 使用场景：大事件、S/A 信号复核、白天抓取失败补救
- 禁止：常态 MO-FR 循环、mobile_use 采价、写 `price_cache.json`

## Calendar 额度

日常循环：4 条 × 5 工作日 = 20 实例/周。保留 10 实例/周给周报、基准线、临时补救或后续扩展。

## 飞书日维度文档

迁移飞书后，每个模块每天生成独立 Markdown 文档草稿，后续用于同步飞书知识库：

- 价格模块：`data/feishu_daily_docs/YYYY-MM-DD/price.md`
- 信号模块：`data/feishu_daily_docs/YYYY-MM-DD/signal.md`

这些文件属于运行态产物，不直接提交 Git；如需沉淀到 GitHub，只提交脱敏后的 `ops_logs/` 摘要。
