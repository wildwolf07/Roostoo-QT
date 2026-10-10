"""Leaderboard decision table: for each possible top-20 return cutoff at the END of the contest,
how likely is our final return to clear it at each exposure level, and what does that cost in
loss risk and composite score?

Uses every 7.5-day stretch of the live ensemble's hourly returns (fees included) since 2023,
scaled by exposure k (vol target = 1.2% x k, gross capped at 95%), with 6 flat days in front
(our late start) for the composite.

Usage: python -m research.risk_table
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.metrics import summary
from research.overlay_study import ensemble_returns

ACTIVE_H = int(7.5 * 24)
FLAT_H = 6 * 24 + 22          # Oct 4 00:00 -> Oct 9 22:00 UTC (live start)
CUTOFFS = (0.0, 0.01, 0.02, 0.03, 0.05, 0.08, 0.12)
KS = (0.75, 1.0, 1.33, 1.6)


def main() -> None:
    base, gross = ensemble_returns()
    b, g = base.values, gross.values
    flat_idx = pd.date_range("2026-10-04", periods=FLAT_H, freq="h", tz="UTC")
    act_idx = pd.date_range(flat_idx[-1] + pd.Timedelta(hours=1), periods=ACTIVE_H, freq="h", tz="UTC")
    rows = []
    for k in KS:
        for s in range(0, len(b) - ACTIVE_H, 12):
            kk = min(k, 0.95 / max(g[s: s + ACTIVE_H].max(), 1e-9))
            eq_act = 1e5 * np.cumprod(1 + kk * b[s: s + ACTIVE_H])
            ret = eq_act[-1] / 1e5 - 1
            rec = {"k": k, "ret": ret}
            if s % 48 == 0:   # composite is slower; subsample
                eq = pd.Series(np.concatenate([np.full(FLAT_H, 1e5), eq_act]), index=flat_idx.append(act_idx))
                rec["composite"] = summary(eq)["composite"]
            rows.append(rec)
    df = pd.DataFrame(rows)
    out = []
    for k, d in df.groupby("k"):
        r = {"exposure": f"{k:.2f}x (vol {1.2 * k:.1f}%/day)"}
        for c in CUTOFFS:
            r[f"P(ret>={c:.0%})"] = f"{(d.ret >= c).mean():.0%}"
        r["P(loss>3%)"] = f"{(d.ret < -0.03).mean():.1%}"
        r["P(loss>5%)"] = f"{(d.ret < -0.05).mean():.1%}"
        r["median composite"] = round(d.composite.dropna().median(), 2)
        out.append(r)
    pd.set_option("display.width", 250)
    print(f"{len(df) // len(KS)} historical 7.5-day stretches (2023-2026), live 25-coin ensemble, fees included")
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    main()
