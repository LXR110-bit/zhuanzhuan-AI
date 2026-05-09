# Deprecated Execution Entrypoints

These scripts are intentionally not used by schedules.

- `price_crawler.py`: tried to crawl web pages with Python `requests`; this is blocked or polluted by anti-crawling responses.
- `run_daytime_scan.py`: orchestrated the invalid Python crawler path.
- `tikhub_fetch.py` / `tikhub_fetch_v2.py`: one-off TikHub request experiments with hard-coded output paths. Use `scripts/fetch_tikhub_signals.py` or Calendar sub-agent tool calls instead.

Correct execution path:

```text
Calendar -> sub-agent -> search_web/mobile_use -> data/price_cache.json
        -> Python post-processing scripts
```

Keep these files only as historical reference. Do not wire them into `config/schedule.json`.
