# 反卷教练 19:00 晚上开工

输出渠道：coze_only

执行步骤：
1. 进入 `skills/anti-involution-coach`。
2. 运行 `python3 scripts/goal_card_manager.py status`。
3. 运行 `python3 scripts/goal_card_manager.py heartbeat 19:00 heartbeat <active_card_found> evening_start success "" coze`。
4. 如果没有 active goal_card，沉默退出。
5. 如果有 active goal_card，只问 21:00 前最小可交付，不重新规划全天。

开场口径：
晚上 2 小时。21:00 前最小能交什么？一句话回我。

禁止事项：
- 不要发送到任何外部群聊。
- 不要携带任何机器人地址、外部推送地址或群聊配置。
