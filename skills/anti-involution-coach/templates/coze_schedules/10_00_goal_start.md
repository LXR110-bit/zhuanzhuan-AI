# 反卷教练 10:00 目标澄清

输出渠道：coze_only

执行步骤：
1. 进入 `skills/anti-involution-coach`。
2. 运行 `python3 scripts/goal_card_manager.py status`。
3. 运行 `python3 scripts/goal_card_manager.py heartbeat 10:00 goal_start <active_card_found> start_phase1 success "" coze`。
4. 如果没有 active goal_card，按 SKILL.md 的 Phase1 发起五题澄清。
5. 如果已经有 active goal_card，只提醒当前目标已存在，并要求主人确认是否继续。

禁止事项：
- 不要发送到任何外部群聊。
- 不要携带任何机器人地址、外部推送地址或群聊配置。
