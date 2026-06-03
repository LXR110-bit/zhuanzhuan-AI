# GitHub 运行日志与飞书知识库规划

## 当前阶段：GitHub 轻量日志

GitHub 当前只存轻量、脱敏、可审计的运行摘要和 Codex 交接单。

允许路径：

```text
ops_logs/runs/YYYY-MM-DD/*.md
ops_logs/schedules/*.md
handoff/codex/*.md
```

禁止路径：

```text
logs/
data/logs/
data/report_cards/
data/outbox/
data/periodic_reports/
大体积截图、录屏、缓存、真实 webhook key、secret、token
```

## Coze 日志 commit 边界

Coze 允许做日志类 commit：

```text
ops-log: <task_name> <YYYY-MM-DD>
```

提交前必须确认 `git status --short` 只有：

```text
ops_logs/
handoff/codex/
```

只要出现代码、配置、模板、文档、版本号、data 原始日志变化，Coze 就必须停止提交并生成 Codex 交接单。

## 后续阶段：飞书知识库

飞书不替代 GitHub。GitHub 是事实源，飞书是可视化检索层。

后续同步对象：

- 运行摘要 → 飞书文档。
- 采价记录摘要 → 飞书多维表格。
- Codex 交接单 → 飞书问题看板。
- 日报/周报 → 飞书知识库归档。

日志中预留字段：

```text
feishu_sync_status: pending
feishu_doc_url:
feishu_bitable_record:
```
