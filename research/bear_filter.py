"""Can a slow market-trend filter on the two long-only sleeves fix 2022 without hurting other years?

Filter: scale the long-only sleeves (momentum long, low-risk long) by `scale` when the market
trend is negative. The L/S sleeves are untouched. Trend measures: equal-weight market 30d return,
BTC price vs its 50-day average. Evaluated 2021-2026 per calendar year and on 14-day windows.

Usage: python -m research.bear_filter
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import StrategyConfig
from bot.metrics import summary
from research.signal_lab import features
from research.stress_test import combined_panel
from research.xs_backtest import Variant, build_tranched


def main() -> None:
    close, qv, tq, fund, prem = combined_panel()
    f = features(close, qv, qv * 0.5, fund, prem)
    feats = {k: f[k] for k in ("vol_72h", "max_ret_24h", "beta_btc", "mom_blend_168_336")}
    mom = (("mom_blend_168_336", 1.0),)
    c = dict(rebalance_h=72, tranches=3, n_side=4, universe=StrategyConfig().universe_size)
    ls = (build_tranched(Variant("a", signals=mom, **c), (close, qv), feats)
          + build_tranched(Variant("c", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, **c), (close, qv), feats)) / 4
    lo = (build_tranched(Variant("b", signals=mom, long_only=True, beta_neutral=False, **c), (close, qv), feats)
          + build_tranched(Variant("d", long_only=True, **c), (close, qv), feats)) / 4
    logr = np.log(close).diff()
    mkt30 = logr.mean(axis=1).rolling(720).sum()
    btc_sma = close["BTC"] / close["BTC"].rolling(1200).mean() - 1
    # decide the filter once per day at 00:00 UTC (like the live rebalance), hold for the day
    def daily_flag(x: pd.Series) -> pd.Series:
        return (x < 0).astype(float).where(x.index.hour == 0).ffill().fillna(0.0)
    flags = {"none": pd.Series(0.0, index=close.index), "mkt30<0": daily_flag(mkt30), "btc<sma50": daily_flag(btc_sma)}
    rets = close.pct_change(fill_method=None).fillna(0)
    rows = []
    for fname, flag in flags.items():
        for scale in ((1.0,) if fname == "none" else (0.5, 0.0)):
            W = ls + lo.mul(1 - flag * (1 - scale), axis=0)
            port = ((W.shift(1) * rets).sum(axis=1) - 0.001 * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:]
            row = {"filter": fname, "long_scale_when_bear": scale}
            daily = port.resample("1D").sum()
            for y, d in daily.groupby(daily.index.year):
                row[f"SR_{y}"] = round(d.mean() / d.std() * np.sqrt(365), 2)
            eq = (1 + port).cumprod() * 100_000
            st = summary(eq)
            row.update(full_SR=round(st["sharpe"], 2), full_ret=f"{st['total_return']:+.0%}", mdd=f"{st['max_drawdown']:.1%}")
            comps, t0 = [], eq.index[0]
            while t0 + pd.Timedelta(days=14) <= eq.index[-1]:
                comps.append(summary(eq.loc[t0: t0 + pd.Timedelta(days=14)])["composite"])
                t0 += pd.Timedelta(days=7)
            row["med_14d_comp"] = round(float(np.median(comps)), 2)
            row["bear_share"] = f"{flag.iloc[800:].mean():.0%}"
            rows.append(row)
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
