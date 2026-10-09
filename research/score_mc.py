"""Scoring-aware study: what does the volatility target do to our contest outcome?

The official window is Oct 4-17 (14 days). Our first ~6 days were flat (bot not yet live),
leaving ~8 active days. We take every contiguous 8-day stretch of the ensemble's
out-of-sample hourly returns (fees included), prepend 6 flat days, scale exposure by k
(k = new vol target / 1.2%, capped by the 95% gross limit) and compute the composite score
exactly as bot/metrics.py does.

Usage: python -m research.score_mc
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.metrics import summary
from research.overlay_study import ensemble_returns
from research.signal_lab import SPLIT

FLAT_DAYS, ACTIVE_DAYS = 6, 8


def main() -> None:
    base, gross = ensemble_returns()
    oos = base[base.index >= pd.Timestamp(SPLIT, tz="UTC")]
    g = gross[gross.index >= pd.Timestamp(SPLIT, tz="UTC")]
    H = ACTIVE_DAYS * 24
    flat_idx = pd.date_range("2026-10-04", periods=FLAT_DAYS * 24, freq="h", tz="UTC")
    act_idx = pd.date_range(flat_idx[-1] + pd.Timedelta(hours=1), periods=H, freq="h", tz="UTC")
    rows = []
    for k in (0.75, 1.0, 1.33, 1.6):
        for s in range(0, len(oos) - H, 12):
            r = oos.values[s: s + H]
            kk = min(k, 0.95 / max(g.values[s: s + H].max(), 1e-9))   # respect gross cap
            eq_act = 100_000 * np.cumprod(1 + kk * r)
            eq = pd.Series(np.concatenate([np.full(len(flat_idx), 100_000.0), eq_act]),
                           index=flat_idx.append(act_idx))
            st = summary(eq)
            rows.append({"k": k, "ret": st["total_return"], "mdd": st["max_drawdown"],
                         "composite": st["composite"], "sortino": st["sortino"], "calmar": st["calmar"]})
    df = pd.DataFrame(rows)
    out = df.groupby("k").agg(
        n=("ret", "size"), median_ret=("ret", "median"), p_ret_gt_0=("ret", lambda x: (x > 0).mean()),
        p_ret_gt_1pct=("ret", lambda x: (x > 0.01).mean()), p_ret_gt_2pct=("ret", lambda x: (x > 0.02).mean()),
        p_ret_gt_4pct=("ret", lambda x: (x > 0.04).mean()), p_ret_lt_m3pct=("ret", lambda x: (x < -0.03).mean()),
        median_mdd=("mdd", "median"), p95_mdd=("mdd", lambda x: x.quantile(0.95)),
        median_comp=("composite", "median"), p75_comp=("composite", lambda x: x.quantile(0.75)))
    pd.set_option("display.width", 220)
    print(f"{ACTIVE_DAYS}-day active stretches from OOS ({oos.index[0].date()} -> {oos.index[-1].date()}), "
          f"{FLAT_DAYS} flat days prepended; k = exposure multiple of the 1.2%/day target")
    print(out.round(4).to_string())


if __name__ == "__main__":
    main()
