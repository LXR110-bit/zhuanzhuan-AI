# Bug：反卷教练消息误推到行情播报企微群

## 问题描述
2026-05-20 19:00，反卷教练19:00晚上开工节点触发的coaching消息（"晚上2小时，21:00前最小能交什么？"）被推送到了行情播报企微webhook，出现在"行情咨询播报助手"群中。

## 影响范围
- 企微群收到与行情无关的coaching消息，干扰业务群信息流
- 用户隐私风险：coaching消息包含工作进度、交付状态等个人信息

## 根因
反卷教练的日程工单（description）中包含了企微webhook URL，执行session在处理时将coaching提醒也推到了该webhook。

## 修复方案
1. **立即**：coaching消息只在扣子主对话推送，不进企微
2. **工单修正**：从反卷教练6个日程工单的description中移除企微webhook引用
3. **代码层面**：coaching相关的heartbeat/review/summary推送逻辑增加渠道白名单检查，仅允许coze渠道

## 仓库修复状态
- 2026-05-21：反卷教练已迁移到独立仓库 `https://github.com/LXR110-bit/zhuanzhuan-anti-coach.git`
- 独立仓已包含渠道策略、6个扣子日程描述模板、heartbeat `output_channel=coze` 校验和日程污染校验脚本
- 行情仓不再维护可执行 coaching skill，只保留本 issue 作为事故记录

## 验证命令
```bash
cd /Users/lilixiaoran/工作/转转/zhuanzhuan-anti-coach
python3 -m py_compile scripts/goal_card_manager.py scripts/validate_channels.py
python3 scripts/validate_channels.py
GOAL_CARD_DIR=/tmp/anti-involution-test python3 scripts/goal_card_manager.py heartbeat 19:00 heartbeat true evening_start success ok coze
GOAL_CARD_DIR=/tmp/anti-involution-test python3 scripts/goal_card_manager.py heartbeat 19:00 heartbeat true evening_start success ok wecom
```

最后一条应返回失败，用于确认非 coze 渠道被拒绝。

## 扣子后台同步清单
- 将10:00日程description替换为 `templates/coze_schedules/10_00_goal_start.md`
- 将12:00日程description替换为 `templates/coze_schedules/12_00_morning_close.md`
- 将13:30日程description替换为 `templates/coze_schedules/13_30_afternoon_start.md`
- 将18:00日程description替换为 `templates/coze_schedules/18_00_dinner_handoff.md`
- 将19:00日程description替换为 `templates/coze_schedules/19_00_evening_start.md`
- 将21:00日程description替换为 `templates/coze_schedules/21_00_daily_close.md`
- 每条日程description都必须只出现 `coze_only`，不得包含任何外部群聊或机器人地址配置

## 规则记录
- 行情播报webhook（5f161534-faed-49a3-a0da-1068ebbce0ea）只用于：日报卡片、异动信号、新品信号、微博信号
- coaching消息（反卷教练6个节点）只通过扣子主对话推送

## 时间线
- 2026-05-20 19:06:31 — bug触发，coaching消息出现在企微群
- 2026-05-20 20:44 — 用户发现并反馈
- 2026-05-20 20:45 — 记录MEMORY.md + 创建本issue
