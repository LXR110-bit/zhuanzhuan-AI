# 白天异动检测

本目录恢复原架构中的“白天异动检测”模块位置，用于给外部日程和旧文档保留稳定入口。

当前执行入口：

```bash
python3 ../scripts/run_daytime_scan.py run --slot HH:MM
```

白天异动检测固定时段：

```text
07:30 / 12:00 / 17:30
```

21:00 是独立的晚间全量检测：

```bash
python3 ../scripts/run_daytime_scan.py run --slot 21:00
```

数据不再在本目录内维护第二份事实源：

- 标准价格缓存：`../data/price_cache.json`
- 扫描状态：`../data/daytime_scan_status.json`
- 统一品类配置：`../config/categories.json`
- 统一阈值配置：`../config/thresholds.json`

如需给旧流程读取，可把本目录视为兼容入口；实际运行仍以 `../config/schedule.json` 为准。
