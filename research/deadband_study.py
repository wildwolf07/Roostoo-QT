"""Deadband study: the live executor skips trades smaller than `deadband` x equity (and never
opens positions smaller than that). How does that change results vs the research backtest,
which trades every weight change? Held weights follow the live rule: trade a coin to its
target only if |target - held| >= deadband; always exit when the target is zero.

Usage: python -m research.deadband_study
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.metrics import summary
from research.overlay_study import ensemble_returns  # noqa: F401  (keeps import side effects consistent)
from research.robustness import _STATE, _init
from research.ablation import build
from research.signal_lab import SPLIT


def held_weights(W: pd.DataFrame, db: float) -> pd.DataFrame:
    w = W.values
    out = np.zeros_like(w)
    h = np.zeros(w.shape[1])
    for t in range(w.shape[0]):
        tgt = w[t]
        if t == 0 or not np.array_equal(tgt, w[t - 1]):
            diff = np.abs(tgt - h)
            exit_ = (tgt == 0) & (h != 0)
            move = (diff >= db) | exit_
            h = np.where(move, tgt, h)
        out[t] = h
    return pd.DataFrame(out, index=W.index, columns=W.columns)


def main() -> None:
    _init()
    W = sum(build(n)[1] for n in ("mom_ls", "mom_lo", "mom_f", "lowrisk_lo")) / 4
    close = _STATE["close"]
    rets = close.pct_change(fill_method=None).fillna(0)
    print("deadband | Sharpe full / IS / OOS | median 14d composite IS / OOS | turnover/day | mean |held-target| ")
    for db in (0.0, 0.0025, 0.005, 0.01, 0.02):
        Hd = held_weights(W, db)
        port = ((Hd.shift(1) * rets).sum(axis=1) - 0.001 * Hd.diff().abs().sum(axis=1).fillna(0)).iloc[800:]
        eq = (1 + port).cumprod() * 1e5
        out = []
        for seg in (port, port[port.index < SPLIT], port[port.index >= SPLIT]):
            d = seg.resample("1D").sum()
            out.append(d.mean() / d.std() * np.sqrt(365))
        comps = {"IS": [], "OOS": []}
        t0 = eq.index[0]
        while t0 + pd.Timedelta(days=14) <= eq.index[-1]:
            c = summary(eq.loc[t0: t0 + pd.Timedelta(days=14)])["composite"]
            comps["IS" if t0 < pd.Timestamp(SPLIT, tz="UTC") else "OOS"].append(c)
            t0 += pd.Timedelta(days=7)
        te = (Hd - W).abs().sum(axis=1).iloc[800:].mean()
        to = Hd.diff().abs().sum(axis=1).iloc[800:].mean() * 24
        print(f"{db:7.2%}  | {out[0]:.2f} / {out[1]:.2f} / {out[2]:.2f} | {np.median(comps['IS']):.2f} / "
              f"{np.median(comps['OOS']):.2f} | {to:.3f} | {te:.3f}")


if __name__ == "__main__":
    main()
