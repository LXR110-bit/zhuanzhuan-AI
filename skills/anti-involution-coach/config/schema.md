# Schema

## goal_cards

One day can contain multiple goal cards, but the manager enforces that only one can be active at a time.

Required fields:
- `card_date`: Local date in Asia/Shanghai, formatted as `YYYY-MM-DD`.
- `card_index`: 1-based index within the day.
- `boss_want`: What the boss/user actually wants (Q1).
- `deliverable`: The most important deliverable today (Q2).
- `min_version`: The minimum viable shape of the deliverable (Q3).
- `deadline`: Deadline or expected handoff time.
- `trap_forecast`: What would make today wasted (Q4).
- `first_cut`: The first concrete cut to start with (Q5).
- `status`: One of `active`, `completed`, `abandoned`.

Recommended future fields:
- `deliverable_acceptance`: What counts as done.
- `next_30min_action`: The next concrete action.

## reviews

Each review must belong to an existing goal card. The manager rejects orphan reviews.

Required fields:
- `card_date`: Local date in Asia/Shanghai.
- `card_index`: Related goal card index.
- `review_index`: 1-based index for this card.
- `did_what`: Actual concrete action in the last block.
- `output`: Usable output or evidence.
- `verdict`: One of `在轨`, `跑偏`, `伪装忙碌`.
- `reason`: Why this verdict was chosen.
- `next_action`: Next concrete action.

Recommended future field:
- `output_evidence`: Link, file, message, table, draft, or other proof that output exists.

## daily_summaries

Daily summary is created at 21:00 or when the user explicitly asks to close the day.

Required fields:
- `summary_date`: Local date in Asia/Shanghai.
- `summary_index`: 1-based index within the day.
- `final_output`: What was finally delivered.
- `goal_delta`: Gap between morning goal and actual result.
- `pretend_effort`: Most obvious fake-effort segment.
- `effective_action`: Action that truly moved output forward.
- `verdict`: One of `有效推进`, `部分推进`, `假装努力`.
- `tomorrow_first_cut`: First concrete action for tomorrow.
- `coach_note`: Short coach summary, under 200 Chinese characters when possible.

## heartbeat_logs

Diagnostic layer for external scheduler (e.g. Coze) heartbeats. Every heartbeat MUST write a log entry, even if it skips action. The manager validates `event_type`, `active_card_found`, and `push_status`.

Required fields:
- `heartbeat_time`: Local timestamp.
- `node`: Schedule node, such as `10:30`, `12:00`, `21:00`.
- `event_type`: One of `goal_start`, `heartbeat`, `segment_close`, `daily_close`.
- `goal_card_path`: JSON file path used by the run.
- `active_card_found`: Boolean.
- `action_taken`: What the run attempted.
- `push_status`: One of `success`, `failed`, `skipped`, `unknown`.
- `reason`: Why it succeeded, failed, or skipped.
- `output_channel`: Must be `coze`. Coaching messages reject every other output channel.
