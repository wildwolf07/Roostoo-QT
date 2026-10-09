"""Stress test of the live ensemble on 2021-2022 (data never used for design): the 2021 bull
run, the May 2022 LUNA collapse, the June 2022 3AC/Celsius deleveraging and the Nov 2022 FTX crash.

Usage: python -m research.download_pre && python -m research.stress_test
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import ROOT, StrategyConfig
from bot.metrics import summary
from research.signal_lab import EXCLUDE, features, load_panel
from research.xs_backtest import Variant, build_tranched, evaluate

PRE = ROOT / "data" / "research_pre"
EVENTS = {"LUNA collapse": ("2022-05-07", "2022-05-13"), "3AC/Celsius": ("2022-06-10", "2022-06-19"),
          "FTX crash": ("2022-11-06", "2022-11-10")}


def combined_panel():
    close, qv, tq, fund, prem = load_panel()
    pc, pq = {}, {}
    for f in sorted(PRE.glob("spot_*.parquet")):
        coin = f.stem.split("_", 1)[1]
        if coin in EXCLUDE:
            continue
        d = pd.read_parquet(f)
        d = d[d.index < close.index[0]]
        pc[coin], pq[coin] = d["close"], d["quote_volume"]
    pre_c, pre_q = pd.DataFrame(pc), pd.DataFrame(pq)
    c = pd.concat([pre_c, close]).sort_index()
    q = pd.concat([pre_q, qv]).sort_index()
    c = c[~c.index.duplicated()]
    q = q[~q.index.duplicated()].reindex(c.index)
    empty = pd.DataFrame(index=c.index)
    return c, q, empty, empty, empty


def main() -> None:
    close, qv, tq, fund, prem = combined_panel()
    print(f"panel {close.index[0].date()} -> {close.index[-1].date()}, coins with 2021 data: "
          f"{int(close.loc[pd.Timestamp('2021-03-01', tz='UTC')].notna().sum())}")
    f = features(close, qv, qv * 0.5, fund, prem)
    import os
    momf = os.environ.get("MOMFEAT", "mom_blend_168_336")
    feats = {k: f[k] for k in ("vol_72h", "max_ret_24h", "beta_btc", momf)}
    mom = ((momf, 1.0),)
    print("momentum feature:", momf)
    c = dict(rebalance_h=72, tranches=3, n_side=4, universe=StrategyConfig().universe_size)
    sleeves = [Variant("a", signals=mom, **c), Variant("b", signals=mom, long_only=True, beta_neutral=False, **c),
               Variant("c", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, **c), Variant("d", long_only=True, **c)]
    W = sum(build_tranched(v, (close, qv), feats) for v in sleeves) / 4
    stats = evaluate("ensemble", W, close, 0.001)
    print("calendar-year Sharpe:", {k: round(v, 2) for k, v in stats.items() if k.startswith("SR_")})
    rets = close.pct_change(fill_method=None).fillna(0)
    port = ((W.shift(1) * rets).sum(axis=1) - 0.001 * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:]
    mkt = rets.mean(axis=1).reindex(port.index)
    btc = rets["BTC"].reindex(port.index)
    for name, (a, b) in EVENTS.items():
        print(f"{name:14s} {a}..{b}: ensemble {port.loc[a:b].sum():+.2%}  market {mkt.loc[a:b].sum():+.2%}  "
              f"BTC {btc.loc[a:b].sum():+.2%}")
    seg = port.loc["2021-02-01":"2022-12-31"]
    eq = (1 + seg).cumprod() * 100_000
    st = summary(eq)
    print(f"2021-02..2022-12: return {st['total_return']:+.1%}  Sharpe {st['sharpe']:.2f}  max DD {st['max_drawdown']:.1%}"
          f"  (BTC {close['BTC'].loc[:'2022-12-31'].iloc[-1] / close['BTC'].loc['2021-02-01':].iloc[0] - 1:+.1%})")
    rows, t0 = [], eq.index[0]
    while t0 + pd.Timedelta(days=14) <= eq.index[-1]:
        s14 = summary(eq.loc[t0: t0 + pd.Timedelta(days=14)])
        rows.append(s14)
        t0 += pd.Timedelta(days=7)
    w = pd.DataFrame(rows)
    print(f"14-day windows 2021-22 (n={len(w)}): median return {w.total_return.median():+.2%}, P(>0) "
          f"{(w.total_return > 0).mean():.0%}, median MDD {w.max_drawdown.median():.2%}, p95 MDD "
          f"{w.max_drawdown.quantile(.95):.2%}, median composite {w.composite.median():.2f}")
    daily = seg.resample("1D").sum()
    print("worst 5 days:", "  ".join(f"{d.date()} {r:+.2%}" for d, r in daily.nsmallest(5).items()))


if __name__ == "__main__":
    main()
