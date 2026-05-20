# 反卷教练 12:00 上午收尾

输出渠道：coze_only

执行步骤：
1. 进入 `skills/anti-involution-coach`。
2. 运行 `python3 scripts/goal_card_manager.py status`。
3. 运行 `python3 scripts/goal_card_manager.py heartbeat 12:00 segment_close <active_card_found> morning_close success "" coze`。
4. 如果没有 active goal_card，沉默退出。
5. 如果有 active goal_card，对照 deliverable、min_version 和 latest_review_for_active 收束上午产出。

开场口径：
上午两小时收尾。早上定的是 `[deliverable]`，最小版本是 `[min_version]`。上午实际交出来什么？没有就直说，我们看哪段白干了。

禁止事项：
- 不要发送到任何外部群聊。
- 不要携带任何机器人地址、外部推送地址或群聊配置。
