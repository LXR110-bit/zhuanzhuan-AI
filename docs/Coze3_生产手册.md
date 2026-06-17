# Coze 3.0 多 Agent 生产手册 V2

> 目标：把革命溯升军团的生产执行从本地桌面迁移到云电脑小MAC mini；GitHub 同时作为生产代码事实源和轻量运行日志/交接单事实源，飞书知识库作为后续可视化与检索层。

## 一、生产拓扑

```text
用户 / Calendar
  ↓
刘司令：只做路由、监督、汇总，不创建代执行日程，不跑业务脚本
  ├─ 侦察兵小C_价格监控：自己的 Calendar → 云电脑小MAC mini → zhuanzhuan-AI/local/dev
  ├─ 侦察兵小B_信号监控：自己的 Calendar → 云电脑小MAC mini → zhuanzhuan-AI/local/dev
  └─ 罗杰指挥官_反卷教练：自己的 Calendar → 云电脑小MAC mini → zhuanzhuan-anti-coach/main
```

硬规则：

- 行情价格日程必须建在价格监控 Agent 自己的 Calendar 空间。
- 行情信号日程必须建在信号监控 Agent 自己的 Calendar 空间。
- 反卷日程必须建在罗杰自己的 Calendar 空间。
- 刘司令不得创建代执行日程。
- 新日程验证跑通前，不删除刘司令空间旧日程。
- 生产执行器默认是云电脑「小MAC mini」，不再依赖 `yinhemanyouzhinan.local`。

## 二、云电脑生产执行规则

云电脑固定工作目录：

```text
~/coze-production/zhuanzhuan-AI
~/coze-production/zhuanzhuan-anti-coach
```

每次执行前必须在云电脑上做：

```bash
git fetch origin
git checkout <生产分支>
git pull --ff-only origin <生产分支>
git rev-parse --short HEAD
```

生产分支：

| Agent | 仓库 | 分支 |
|---|---|---|
| 侦察兵小C_价格监控 | `github.com/LXR110-bit/zhuanzhuan-AI.git` | `local/dev` |
| 侦察兵小B_信号监控 | `github.com/LXR110-bit/zhuanzhuan-AI.git` | `local/dev` |
| 罗杰指挥官_反卷教练 | `github.com/LXR110-bit/zhuanzhuan-anti-coach.git` | `main` |

Coze/Agent 在云电脑上只允许：

- 拉取 GitHub 生产代码。
- 运行既有脚本。
- 写入 `ops_logs/` 和 `handoff/codex/`。
- 提交 `ops-log:` 前缀的日志类 commit。

禁止：

- 修改业务代码、配置、模板和版本号。
- 修 bug、重构、格式化代码。
- 把真实 webhook key、secret、token 写入 description、日志或 commit。
- 将原始大日志、大图、缓存、运行态大 JSON 提交到 GitHub。

## 三、GitHub 日志规则

当前阶段 GitHub 是轻量运行日志和 Codex 交接单的事实源；飞书知识库后续同步。

允许 Coze 提交的日志路径：

```text
ops_logs/runs/YYYY-MM-DD/*.md
ops_logs/schedules/*.md
handoff/codex/*.md
```

日志 commit 规则：

```bash
git status --short
# 确认只有 ops_logs/ 或 handoff/codex/ 变更
git add ops_logs/ handoff/codex/
git commit -m "ops-log: <任务名> <YYYY-MM-DD>"
git push origin <生产分支>
```

如果 `git status --short` 出现 `scripts/`、`config/`、`docs/`、`templates/`、`policy/`、`README` 等代码/配置/文档改动，Coze 必须停止提交并输出 `handoff/codex/` 问题单。

## 四、日志模板

运行摘要必须包含：

```text
任务名称：
Agent：
触发方式：Calendar / 手动 / 测试
执行环境：云电脑 小MAC mini
仓库：
分支：
commit：
开始/结束时间：
执行命令：
产物路径：
推送渠道：扣子 / 企微 / 飞书 / 无
结果：成功 / 失败 / 部分成功
异常：
是否需要 Codex：是 / 否
```

Codex 交接单必须包含：

```text
问题标题：
影响模块：行情 / 反卷 / 调度 / 日志
发现时间：
复现步骤：
失败日志摘要：
期望行为：
实际行为：
影响范围：
建议优先级：P0 / P1 / P2
Coze 已做动作：只核查 / 已停用 / 已回退
禁止 Coze 自修：是
```

## 五、日程 description 写法

统一写法：

```text
【生产执行器】云电脑 小MAC mini
【代码事实源】GitHub 仓库 + 生产分支
【执行前置】git fetch origin && git checkout <branch> && git pull --ff-only origin <branch>
【运行】执行既有脚本，不改代码
【日志】写入 ops_logs/runs/YYYY-MM-DD/<task>.md
【失败】写入 handoff/codex/<issue>.md，交给 Codex
【提交】仅当 git status 只有 ops_logs/ 或 handoff/codex/ 时，允许 ops-log commit/push
【禁止】不提交代码/配置/原始日志/密钥/大体积产物
```

行情日程必须由小B创建；反卷日程必须由罗杰创建。

## 六、飞书知识库后续同步

飞书知识库暂不作为本轮生产依赖。本轮只在日志中预留字段：

```text
feishu_sync_status: pending / synced / skipped
feishu_doc_url:
feishu_bitable_record:
```

后续飞书定位：

- 运行摘要可读化。
- 采价选项、截图链接、推送结果多维表格化。
- Codex 问题单看板化。
- 日报/周报沉淀为可搜索知识库。

## 七、验证顺序

1. 小B、罗杰分别创建云电脑非循环测试事件。
2. 测试只执行：`pwd`、`python3 -V`、`git --version`、`git status --short --branch`。
3. 测试 GitHub 日志提交，只提交 `ops_logs/` 或 `handoff/codex/`。
4. 小B先建 1 条行情测试任务包；罗杰先建 1 条反卷测试事件。
5. 新 Agent 空间日程跑通后，刘司令输出旧日程待删除清单，等用户确认后删除。
```

## 八、行情双 Agent 与飞书触达

行情由两个应用/机器人触达同一个飞书群：

| Agent | 飞书环境变量 | 消息前缀 | 日维度文档 |
|---|---|---|---|
| `侦察兵小C_价格监控` | `FEISHU_PRICE_WEBHOOK_URL` | `【价格监控】` | `data/feishu_daily_docs/YYYY-MM-DD/price.md` |
| `侦察兵小B_信号监控` | `FEISHU_SIGNAL_WEBHOOK_URL` | `【信号监控】` | `data/feishu_daily_docs/YYYY-MM-DD/signal.md` |

规则：

- 两个飞书机器人可以在同一个飞书群，但必须用不同应用/机器人名称或消息前缀区分。
- 日报类价格消息由价格 Agent 推送；S/A 级热点信号由信号 Agent 推送。
- B 级信号只进入扣子/日志/日报摘要，默认不打扰飞书群。
- 每次飞书推送同时生成一份日维度 Markdown 文档草稿，供后续同步飞书知识库。
- 真实 webhook 只允许存在 `.env` 或环境变量，不得进入 description、日志或 Git。
