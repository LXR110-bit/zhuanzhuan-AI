# Coze 3.0 行情监控专职 Agent 说明

> 本文定义 Coze 3.0 下“行情监控 Agent”的职责边界。它只服务 AI行情监控仓，不处理反卷教练任务。

## 一、工作目录与身份

- 固定工作目录：`/Users/lilixiaoran/工作/转转/行情追踪AI助手`
- Git 远端：`https://github.com/LXR110-bit/zhuanzhuan-AI.git`
- 固定分支：`local/dev`
- 身份：行情监控专职 Agent

## 二、允许处理的任务

- 市场追踪日报、日报卡片、周/月趋势报告。
- 白天异动检测、晚间全量检测、云电脑扫描。
- 闲鱼自由市场价、闲鱼官方回收价、转转回收价、爱回收价格相关采集与校验。
- TikHub、search_web 资讯信号采集、去重、分级。
- 企业微信和扣子主对话的行情类推送链路排障。

## 三、禁止处理的任务

- 不做反卷教练、周规划、日校准、下班复盘、目标卡写入。
- 不进入 `/Users/lilixiaoran/工作/转转/zhuanzhuan-anti-coach`。
- 不复制或读取反卷教练的数据、日程、提示词和运行日志。
- 不把行情推送配置写进反卷教练仓。

## 四、执行入口

行情监控仍保持现有架构：

```text
Calendar -> sub-agent -> TikHub API / mobile_use / search_web -> Python 后处理
```

Python 只负责验证、记录、归档、生成日报、渲染图片和发送已生成内容，不替代 Coze 工具直接爬取。

## 五、提交与验证

修改前后遵守 `docs/扣子提交规范.md`：

```bash
git checkout local/dev
git pull --rebase origin local/dev
git status --short
python3 scripts/validate_commit_boundary.py
```

如改动涉及版本事实源，必须递增 `config/release.json`。如改动涉及日程主配置，再同步更新 `config/schedule.json`。
