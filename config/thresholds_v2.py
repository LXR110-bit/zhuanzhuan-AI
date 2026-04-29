"""Quantitative thresholds for volume-price scenario judgment.

Values use decimal ratios instead of percentage points:
0.15 means +15%, -0.08 means -8%.
"""

VOLUME_PRICE_THRESHOLDS = {
    "volume_up": 0.15,
    "volume_down": -0.15,
    "price_up": 0.05,
    "price_down": -0.05,
}

PANIC_THRESHOLDS = {
    "volume_drop": -0.30,
    "price_drop": -0.10,
}

SUPPLY_DEMAND_THRESHOLDS = {
    "supply_shock_ratio": 1.50,
    "demand_collapse_ratio": 0.70,
}
