"""Parameter study on independent 14-day windows (each starts fresh at $100k, like the contest).

Usage: python -m backtest.sweep
"""
from __future__ import annotations

import itertools
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import pandas as pd

from backtest.engine import load_data, run
from bot.config import StrategyConfig

WINDOW_DAYS, STEP_DAYS = 14, 7
START, END = "2025-06-01", "2026-10-09"


def windows():
    t = pd.Timestamp(START, tz="UTC")
    end = pd.Timestamp(END, tz="UTC")
    while t + pd.Timedelta(days=WINDOW_DAYS) <= end:
        yield t, t + pd.Timedelta(days=WINDOW_DAYS)
        t += pd.Timedelta(days=STEP_DAYS)


def evaluate(args):
    name, scfg_kwargs, run_kwargs = args
    closes, vols = load_data(StrategyConfig().whitelist)
    scfg = replace(StrategyConfig(), **scfg_kwargs)
    rows = []
    for a, b in windows():
        _, st = run(str(a), str(b), scfg=scfg, closes=closes, vols=vols, **run_kwargs)
        rows.append(st)
    df = pd.DataFrame(rows)
    return {
        "config": name, "n": len(df),
        "med_ret%": 100 * df.total_return.median(), "mean_ret%": 100 * df.total_return.mean(),
        "p(ret>0)": (df.total_return > 0).mean(), "med_mdd%": 100 * df.max_drawdown.median(),
        "worst_mdd%": 100 * df.max_drawdown.max(), "med_comp": df.composite.median(),
        "mean_comp": df.composite.clip(-20, 50).mean(), "trades/day": df.trades_per_day.mean(),
        "fees%": 100 * df.fees_pct.mean(),
    }


def grid():
    base = {"min_gross": 0.0, "history_bars": 500, "mom_lookbacks": (168, 336),
            "rebalance_hours": 24, "tranches": 3, "tranche_spacing_hours": 24, "use_regime_gate": False}
    return [
        ("trend_n5_tranched", {**base, "style": "trend", "max_positions": 5}, {"deadband": 0.02}),
        ("xs_n3_tranched", {**base, "style": "xs", "max_positions": 3, "short_max_positions": 3}, {"deadband": 0.02}),
        ("blend_n4_tranched", {**base, "style": "blend", "max_positions": 4, "short_max_positions": 3}, {"deadband": 0.02}),
        ("blend_n4_tranched_vt15", {**base, "style": "blend", "max_positions": 4, "short_max_positions": 3,
                                    "target_daily_vol": 0.015}, {"deadband": 0.02}),
    ]


if __name__ == "__main__":
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(evaluate, grid()))
    df = pd.DataFrame(results).sort_values("med_comp", ascending=False)
    pd.set_option("display.width", 250)
    print(df.round(3).to_string(index=False))
    df.to_csv("data/sweep_results.csv", index=False)
