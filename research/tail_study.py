"""Tail-risk study for the live ensemble: worst hours/days, the 2025-10-10 crash, and the
effect of per-coin trailing stops (live: max(6%, min(15%, 4 x daily vol)), 6h cooldown).

Usage: python -m research.tail_study
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.metrics import summary
from research.ablation import build
from research.robustness import _STATE, _init
from research.signal_lab import SPLIT


def ensemble_W() -> pd.DataFrame:
    _init()
    names = ["mom_ls", "mom_lo", "mom_f", "lowrisk_lo"]
    return sum(build(n)[1] for n in names) / 4


def apply_stops(W: pd.DataFrame, close: pd.DataFrame, vol_mult: float, smin: float, smax: float,
                cooldown_h: int = 6) -> pd.DataFrame:
    """Zero a coin's weight once its price moves against the position by the stop distance from
    its best price since entry; it may re-enter at the next daily rebalance after the cooldown."""
    px = close.ffill().values
    logr = np.log(close).diff()
    dvol = (logr.rolling(72, min_periods=48).std() * np.sqrt(24)).values
    w = W.values.copy()
    out = np.zeros_like(w)
    best = np.full(w.shape[1], np.nan)
    stopped_until = np.full(w.shape[1], -1)
    side = np.zeros(w.shape[1])
    for t in range(w.shape[0]):
        rebalance_hour = (t % 24 == 0)
        for j in range(w.shape[1]):
            target = w[t, j]
            if stopped_until[j] >= 0:
                if t < stopped_until[j] or not rebalance_hour:
                    out[t, j] = 0.0
                    continue
                stopped_until[j] = -1
            s = np.sign(target)
            if s == 0 or np.isnan(px[t, j]):
                side[j], best[j] = 0, np.nan
                out[t, j] = 0.0
                continue
            if s != side[j]:
                side[j], best[j] = s, px[t, j]
            best[j] = max(best[j], px[t, j]) if s > 0 else min(best[j], px[t, j])
            v = dvol[t, j] if not np.isnan(dvol[t, j]) else 0.04
            dist = min(smax, max(smin, vol_mult * v))
            hit = px[t, j] <= best[j] * (1 - dist) if s > 0 else px[t, j] >= best[j] * (1 + dist)
            if hit:
                stopped_until[j] = t + cooldown_h
                side[j], best[j] = 0, np.nan
                out[t, j] = 0.0
            else:
                out[t, j] = target
    return pd.DataFrame(out, index=W.index, columns=W.columns)


def pnl(W: pd.DataFrame, close: pd.DataFrame) -> pd.Series:
    rets = close.pct_change(fill_method=None).fillna(0)
    return ((W.shift(1) * rets).sum(axis=1) - 0.001 * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:]


def main() -> None:
    W = ensemble_W()
    close = _STATE["close"]
    port = pnl(W, close)
    btc = close["BTC"].pct_change(fill_method=None).reindex(port.index).fillna(0)
    mkt = close.pct_change(fill_method=None).mean(axis=1).reindex(port.index).fillna(0)
    print("worst 8 hours (ensemble vs BTC vs equal-weight market):")
    for t in port.nsmallest(8).index:
        print(f"  {t}  ens {port[t]:+.2%}  btc {btc[t]:+.2%}  mkt {mkt[t]:+.2%}")
    daily = port.resample("1D").sum()
    print("worst 8 days:", "  ".join(f"{d.date()} {r:+.2%}" for d, r in daily.nsmallest(8).items()))
    print("best 5 days:", "  ".join(f"{d.date()} {r:+.2%}" for d, r in daily.nlargest(5).items()))
    crash = port.loc["2025-10-10":"2025-10-11"]
    print(f"2025-10-10/11 crash window: ensemble {crash.sum():+.2%}, equal-weight market "
          f"{mkt.loc['2025-10-10':'2025-10-11'].sum():+.2%}, BTC {btc.loc['2025-10-10':'2025-10-11'].sum():+.2%}")
    net = W.sum(axis=1).iloc[800:]
    print(f"net exposure: mean {net.mean():+.2f}, 5-95% [{net.quantile(.05):+.2f}, {net.quantile(.95):+.2f}]; "
          f"gross mean {W.abs().sum(axis=1).iloc[800:].mean():.2f}")
    print(f"correlation of daily returns with market: {daily.corr(mkt.resample('1D').sum()):.2f}")

    print("\nstop settings (full period / IS / OOS):")
    for label, args in (("no stops", None), ("live: 4x vol, 6-15%", (4.0, 0.06, 0.15)),
                        ("old: 2.5x vol, 3-8%", (2.5, 0.03, 0.08)), ("wide: 6x vol, 10-25%", (6.0, 0.10, 0.25))):
        Ws = W if args is None else apply_stops(W, close, *args)
        p = pnl(Ws, close)
        res = []
        for name, seg in (("full", p), ("IS", p[p.index < SPLIT]), ("OOS", p[p.index >= SPLIT])):
            st = summary((1 + seg).cumprod() * 100_000)
            res.append(f"{name}: SR {st['sharpe']:.2f} ret {st['total_return']:+.1%} mdd {st['max_drawdown']:.1%}")
        print(f"  {label:22s} " + " | ".join(res))


if __name__ == "__main__":
    main()
