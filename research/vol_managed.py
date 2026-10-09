"""Volatility-managed ensemble (Moreira & Muir 2017; Barroso & Santa-Clara 2015): scale the whole
book daily by clip(target / realised vol of the strategy's own last-N-day returns, lo, hi), capped
at 95% gross. Evaluated on 2021-2026 (incl. unseen 2021-22) per year and on 14-day windows.

Usage: python -m research.vol_managed
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import StrategyConfig
from bot.metrics import summary
from research.signal_lab import SPLIT, features
from research.stress_test import combined_panel
from research.xs_backtest import Variant, build_tranched


def main() -> None:
    close, qv, tq, fund, prem = combined_panel()
    f = features(close, qv, qv * 0.5, fund, prem)
    feats = {k: f[k] for k in ("vol_72h", "max_ret_24h", "beta_btc", "mom_blend_168_336")}
    mom = (("mom_blend_168_336", 1.0),)
    c = dict(rebalance_h=72, tranches=3, n_side=4, universe=StrategyConfig().universe_size)
    sleeves = [Variant("a", signals=mom, **c), Variant("b", signals=mom, long_only=True, beta_neutral=False, **c),
               Variant("c", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, **c), Variant("d", long_only=True, **c)]
    W = sum(build_tranched(v, (close, qv), feats) for v in sleeves) / 4
    rets = close.pct_change(fill_method=None).fillna(0)
    raw = (W.shift(1) * rets).sum(axis=1)               # unscaled hourly strategy return (pre-fee)
    gross = W.abs().sum(axis=1)
    rows = []
    for label, lookback, lo, hi in (("none", None, 1, 1), ("7d, 0.5-1.5", 7, 0.5, 1.5),
                                     ("14d, 0.5-1.5", 14, 0.5, 1.5), ("7d, 0.5-1.0 (down only)", 7, 0.5, 1.0)):
        if lookback is None:
            k = pd.Series(1.0, index=W.index)
        else:
            daily = raw.resample("1D").sum()
            rv = daily.rolling(lookback, min_periods=lookback).std().shift(1)      # known at day start
            target = daily.std()                                                  # long-run strategy vol
            kd = (target / rv).clip(lo, hi).fillna(1.0)
            k = kd.reindex(W.index, method="ffill").fillna(1.0)
            k = np.minimum(k, 0.95 / gross.replace(0, np.nan)).fillna(1.0)        # gross cap
        Wk = W.mul(k, axis=0)
        port = ((Wk.shift(1) * rets).sum(axis=1) - 0.001 * Wk.diff().abs().sum(axis=1).fillna(0)).iloc[800:]
        eq = (1 + port).cumprod() * 1e5
        row = {"variant": label}
        d = port.resample("1D").sum()
        for y, g in d.groupby(d.index.year):
            row[f"SR_{y}"] = round(g.mean() / g.std() * np.sqrt(365), 2)
        st = summary(eq)
        row.update(full_SR=round(st["sharpe"], 2), ret=f"{st['total_return']:+.0%}", mdd=f"{st['max_drawdown']:.1%}")
        comps = {"pre-2023": [], "IS": [], "OOS": []}
        t0 = eq.index[0]
        while t0 + pd.Timedelta(days=14) <= eq.index[-1]:
            cmp = summary(eq.loc[t0: t0 + pd.Timedelta(days=14)])["composite"]
            key = "pre-2023" if t0 < pd.Timestamp("2023-01-01", tz="UTC") else ("IS" if t0 < pd.Timestamp(SPLIT, tz="UTC") else "OOS")
            comps[key].append(cmp)
            t0 += pd.Timedelta(days=7)
        row.update({f"comp_{k2}": round(float(np.median(v)), 2) for k2, v in comps.items()})
        rows.append(row)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
