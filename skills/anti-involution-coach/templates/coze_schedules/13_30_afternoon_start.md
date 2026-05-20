# 反卷教练 13:30 下午开工

输出渠道：coze_only

执行步骤：
1. 进入 `skills/anti-involution-coach`。
2. 运行 `python3 scripts/goal_card_manager.py status`。
3. 运行 `python3 scripts/goal_card_manager.py heartbeat 13:30 heartbeat <active_card_found> afternoon_start success "" coze`。
4. 如果没有 active goal_card，沉默退出。
5. 如果有 active goal_card，不重新规划，只接上 latest_review_for_active 的 next_action。

开场口径：
下午开工。早上定的是 `[deliverable]`，上一段到了 `[output]`。下午第一刀：30 分钟内做完 `[next_action]`。开始吧。

禁止事项：
- 不要发送到任何外部群聊。
- 不要携带任何机器人地址、外部推送地址或群聊配置。
