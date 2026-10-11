"""Survivorship-bias test: run the live ensemble on (a) our survivor whitelist (coins live on
Roostoo today) and (b) a BROAD point-in-time universe that adds ~40 coins that were large at
some point since 2021, including coins later delisted or renamed (EOS, FTM, MKR, WAVES, MATIC,
RNDR, FTT through the FTX collapse). In both cases the strategy picks the 25 most liquid coins
by trailing 24h volume at each rebalance, so (b) only uses information available at the time.

Usage: python -m research.download_broad && python -m research.survivorship
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import ROOT, StrategyConfig
from bot.metrics import summary
from research.signal_lab import SPLIT, features
from research.stress_test import combined_panel
from research.xs_backtest import Variant, build_tranched

BROAD = ROOT / "data" / "research_broad"


def broad_panel(close: pd.DataFrame, qv: pd.DataFrame, only: tuple | None = None):
    c, q = dict(close.items()), dict(qv.items())
    for f in sorted(BROAD.glob("spot_*.parquet")):
        coin = f.stem.split("_", 1)[1]
        if coin in c or (only is not None and coin not in only):
            continue
        d = pd.read_parquet(f)
        c[coin] = d["close"].reindex(close.index)
        q[coin] = d["quote_volume"].reindex(close.index)
    return pd.DataFrame(c), pd.DataFrame(q)


def run(close: pd.DataFrame, qv: pd.DataFrame, label: str, universe: int | None = None) -> dict:
    empty = pd.DataFrame(index=close.index)
    f = features(close, qv, qv * 0.5, empty, empty)
    feats = {k: f[k] for k in ("vol_72h", "max_ret_24h", "beta_btc", "mom_blend_168_336")}
    mom = (("mom_blend_168_336", 1.0),)
    c = dict(rebalance_h=72, tranches=3, n_side=4, universe=universe or StrategyConfig().universe_size)
    sleeves = [Variant("a", signals=mom, **c), Variant("b", signals=mom, long_only=True, beta_neutral=False, **c),
               Variant("c", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, **c), Variant("d", long_only=True, **c)]
    W = sum(build_tranched(v, (close, qv), feats) for v in sleeves) / 4
    rets = close.pct_change(fill_method=None).fillna(0)
    port = ((W.shift(1) * rets).sum(axis=1) - 0.001 * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:]
    eq = (1 + port).cumprod() * 1e5
    row = {"universe": label, "coins_available": close.shape[1]}
    d = port.resample("1D").sum()
    for y, g in d.groupby(d.index.year):
        row[f"SR_{y}"] = round(g.mean() / g.std() * np.sqrt(365), 2)
    st = summary(eq)
    row.update(full_SR=round(st["sharpe"], 2), ret=f"{st['total_return']:+.0%}", mdd=f"{st['max_drawdown']:.1%}")
    comps = {"2021-22": [], "IS": [], "OOS": []}
    t0 = eq.index[0]
    while t0 + pd.Timedelta(days=14) <= eq.index[-1]:
        k = "2021-22" if t0 < pd.Timestamp("2023-01-01", tz="UTC") else ("IS" if t0 < pd.Timestamp(SPLIT, tz="UTC") else "OOS")
        comps[k].append(summary(eq.loc[t0: t0 + pd.Timedelta(days=14)])["composite"])
        t0 += pd.Timedelta(days=7)
    row.update({f"comp_{k}": round(float(np.median(v)), 2) for k, v in comps.items()})
    held = (W.iloc[800:].abs() > 1e-6)
    return row, held


def main() -> None:
    close, qv, *_ = combined_panel()
    survivors = run(close, qv, "survivors (live whitelist)")
    bc, bq = broad_panel(close, qv)
    broad = run(bc, bq, "broad point-in-time")
    rows = [survivors[0], broad[0]]
    pd.set_option("display.width", 250)
    print(pd.DataFrame(rows).to_string(index=False))
    held = broad[1]
    extra = [c for c in held.columns if c not in close.columns]
    share = held[extra].sum(axis=1) / held.sum(axis=1).replace(0, np.nan)
    print(f"\nbroad run: share of held positions in non-whitelist coins: mean {share.mean():.0%}")
    top = held[extra].mean().sort_values(ascending=False).head(10)
    print("most-held non-whitelist coins (fraction of hours held):", {k: round(v, 2) for k, v in top.items()})


if __name__ == "__main__":
    main()
