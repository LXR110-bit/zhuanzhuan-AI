# Coze 3.0 多 Agent 生产手册

> 目标：让 Coze 直接完成“总控 Agent + 行情监控 Agent + 反卷教练 Agent”的日常运行、校验和防串台，不需要用户手动判断该进哪个仓库。

## 一、生产拓扑

```text
用户请求
  ↓
总控 Agent：判断意图、拆分复合任务、选择专职 Agent
  ├─ 行情监控 Agent：/Users/lilixiaoran/工作/转转/行情追踪AI助手
  └─ 反卷教练 Agent：/Users/lilixiaoran/工作/转转/zhuanzhuan-anti-coach
```

总控 Agent 不能运行任何业务脚本；只允许输出路由决定和子任务说明。

## 二、总控 Agent 生产指令

每次收到用户请求，按以下顺序处理：

1. 判断意图是否属于行情、价格、日报、异动、趋势、采价、市场信号。
2. 判断意图是否属于反卷、周规划、日校准、中段感知、下班复盘、目标卡、业务观察、思维差异。
3. 如果两类都包含，拆成两个子任务，分别交给两个专职 Agent。
4. 如果无法判断，先问一句澄清：`你是想看行情监控，还是做工作复盘/规划？`
5. 路由时必须带上目标工作目录，禁止让专职 Agent 自行猜路径。

## 三、行情监控 Agent 生产指令

固定进入：

```bash
cd /Users/lilixiaoran/工作/转转/行情追踪AI助手
```

生产职责：

- 处理行情日报、价格采集、异动检测、趋势报告、行情推送排障。
- 按 `ARCHITECTURE.md` 和 `config/calendar_subagent_schedules.json` 使用现有链路。
- 保持 `Calendar -> sub-agent -> tool calls -> Python 后处理`，不要把 Python 当成直接爬取替代。

修改/发布前必须执行：

```bash
git status --short
python3 scripts/validate_commit_boundary.py
```

如果改动涉及版本事实源，更新 `config/release.json`；如果涉及日程主配置，同步更新 `config/schedule.json`。

## 四、反卷教练 Agent 生产指令

固定进入：

```bash
cd /Users/lilixiaoran/工作/转转/zhuanzhuan-anti-coach
```

生产职责：

- 周日 21:00 周规划。
- 工作日 10:00 日校准。
- 工作日 14:00 中段感知。
- 工作日 18:00 下班复盘。
- 沉淀目标卡、每日复盘、业务观察、思维差异、周作战图。

所有日程必须来自：

```text
templates/coze_schedules/10_00_goal_start.md
templates/coze_schedules/14_00_mid_check.md
templates/coze_schedules/18_00_evening_review.md
templates/coze_schedules/sunday_21_00_weekly_planner.md
```

统一入口：

```bash
python3 scripts/coze_schedule_runner.py <node>
```

修改/发布前必须执行：

```bash
git status --short
python3 scripts/validate_channels.py
python3 scripts/validate_commit_boundary.py
```

如果改动涉及版本事实源，更新 `config/release.json`。

## 五、复合请求处理范式

用户说：`帮我看看明天工作和行情都怎么安排`

总控 Agent 必须拆成：

1. 行情子任务：交给行情监控 Agent，读取行情日报/趋势/异动，给出市场侧判断。
2. 工作子任务：交给反卷教练 Agent，基于周计划和日复盘给出明天工作安排。
3. 总控 Agent 最后合并两个 Agent 的结果，只做摘要，不改写事实。

## 六、发布前总检查

行情仓：

```bash
cd /Users/lilixiaoran/工作/转转/行情追踪AI助手
git status --short
python3 scripts/validate_commit_boundary.py
```

反卷仓：

```bash
cd /Users/lilixiaoran/工作/转转/zhuanzhuan-anti-coach
git status --short
python3 scripts/validate_channels.py
python3 scripts/validate_commit_boundary.py
```

总控 Agent 只有在两边校验都通过后，才能回复“生产配置可启用”。
