# Coze 3.0 行情监控双 Agent 说明 V3

原 `侦察兵小B_行情监控` 拆分为两个更专业的行情 Agent：

| Agent | 职责 | 说明文档 |
|---|---|---|
| `侦察兵小C_价格监控` | 采价、价格校验、日报价格产物、价格推送 | `docs/Coze3_价格监控Agent说明.md` |
| `侦察兵小B_信号监控` | 热点资讯、政策/新品/平台信号、信号分级和推送 | `docs/Coze3_信号监控Agent说明.md` |

## 生产身份

两个 Agent 共用同一个行情仓和生产分支，但 Calendar、记忆、日志、推送身份必须分开。

```text
仓库：github.com/LXR110-bit/zhuanzhuan-AI.git
分支：local/dev
云电脑目录：/root/coze-production/zhuanzhuan-AI
生产执行器：云电脑「小MAC mini」
```

## 日程结构

日常循环只创建 4 条 MO-FR：

| Agent | 时间 | 日程 | 类型 |
|---|---|---|---|
| 价格监控 | 06:00 | 早盘价格全量任务包 | MO-FR 循环 |
| 信号监控 | 08:30 | 早盘信号雷达 | MO-FR 循环 |
| 价格监控 | 10:00 | 价格日报推送任务包 | MO-FR 循环 |
| 信号监控 | 15:30 | 午后信号补扫 | MO-FR 循环 |

机动任务只保留 description 模板，不创建循环：

- 18:00 晚盘价格机动任务包。
- 20:30 晚间信号机动任务包。

完整 description 模板见 `docs/Coze3_行情双Agent日程模板.md`。

## 硬规则

- 价格 Agent 不调用 TikHub/search_web 做热点扩展。
- 信号 Agent 不调用 mobile_use，不写 `data/price_cache.json`。
- 刘司令只路由、监督、汇总，不创建代执行日程。
- 新日程验证跑通前，不删除旧小B日程。
- 飞书 webhook / secret 只放 `.env` 或环境变量，不写入 description、日志或 Git。
- Coze 不修 bug，不改代码/配置，只运行既有脚本并写日志/交接单。
