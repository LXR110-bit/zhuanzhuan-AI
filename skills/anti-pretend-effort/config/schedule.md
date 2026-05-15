# Schedule

## Daily Rhythm

| Time | Node | Action |
|------|------|--------|
| 10:00 | Morning goal card | Start Phase1 if there is no active goal_card. |
| 10:30 | Morning heartbeat | Run Phase2 if active goal_card exists. |
| 11:00 | Morning heartbeat | Run Phase2 if active goal_card exists. |
| 11:30 | Morning heartbeat | Run Phase2 if active goal_card exists. |
| 12:00 | Morning close | Summarize morning output and identify fake-effort segment if no usable output exists. |
| 13:30 | Afternoon start | Read active goal_card and confirm the first 30-minute action. Do not reopen planning. |
| 14:00-17:30 | Afternoon heartbeat | Run Phase2 every 30 minutes if active goal_card exists. |
| 18:00 | Dinner handoff | Close the afternoon segment, record current blocker, and define the 19:00 first action. |
| 19:00 | Evening start | Ask only what can be minimally delivered before 21:00. |
| 19:30 | Evening heartbeat | Run Phase2 if active goal_card exists. |
| 20:00 | Evening heartbeat | Run Phase2 if active goal_card exists. |
| 20:30 | Evening heartbeat | Run Phase2 if active goal_card exists. |
| 21:00 | Daily close | Run Phase3 daily summary and decide final verdict. |

## Rules

- Ordinary 30-minute heartbeats only run inside work blocks: 10:00-12:00, 13:30-18:00, 19:00-21:00.
- 12:00, 18:00, and 21:00 are close/handoff nodes, not normal heartbeats.
- Non-work blocks do not send normal pressure prompts unless the user explicitly asks for review.
- If a heartbeat cannot find an active goal_card, it should log the miss and avoid asking Phase2 questions.
- If the same node fires repeatedly, prefer one concise reminder over duplicate prompts.
