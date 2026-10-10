"""Moonshot study: what would it take to reach the overall #1 return (+37% on Oct 10) in the 7 days
left, and what would trying cost us in our own region's selection?

Compares the adopted endgame lock-in with all-in concentrated bets (95% of equity, long-only, no
leverage on Roostoo spot): the strongest-momentum coin, the most volatile coin, and the top-3
momentum coins. Each is replayed on every historical 7.3-day stretch (2023-26, fees included),
appended to our real contest path. If a field is given, it also reports P(top 20 by return),
P(top 5 by composite) and P(#1 by composite) in our region.

Usage: python -m research.moonshot --banked 0.010 --target 0.374 [--field ...]
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from research.ablation import build
from research.endgame import FEE, HOURS, LIVE, SLEEVES, START, competitor_paths, k_lockin, realised_path, scores
from research.robustness import _STATE, _init


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--banked", type=float, required=True)
    ap.add_argument("--target", type=float, default=0.374, help="return to beat (overall #1 now)")
    ap.add_argument("--now", default="2026-10-10T18:00")
    ap.add_argument("--field", type=float, nargs="*", default=None)
    ap.add_argument("--step", type=int, default=12)
    args = ap.parse_args()

    now = pd.Timestamp(args.now, tz="UTC").floor("1h")
    now_h = int((now - START) / pd.Timedelta(hours=1))
    H = HOURS - now_h
    live_day = int((LIVE.normalize() - START) / pd.Timedelta(days=1)) + 1
    _init()
    close = _STATE["close"]
    rets = close.pct_change(fill_method=None).fillna(0)
    W = sum(build(n)[1] for n in SLEEVES) / len(SLEEVES)
    port = ((W.shift(1) * rets).sum(axis=1) - FEE * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:]
    gross = W.abs().sum(axis=1).iloc[800:].values
    mom = _STATE["feats"]["mom_blend_168_336"].iloc[800:]
    vol = rets.rolling(72).std().iloc[800:]
    R = rets.iloc[800:]
    mkt = R.mean(axis=1).values
    past = realised_path(args.banked, now_h, 0.0011)
    lock = k_lockin(0.01, 0.25)
    to_rebal = (24 - now.hour) % 24

    def path_lockin(s):
        e, k, eq = past[-1], 1.0, []
        for t in range(H):
            if t == to_rebal or (t > to_rebal and (t - to_rebal) % 24 == 0):
                nk = lock(e - 1.0) * (0.5 if now_h + t >= 13 * 24 else 1.0)
                e *= 1 - FEE * abs(nk - k) * gross[s + t]
                k = nk
            e *= 1 + k * port.iat[s + t]
            eq.append(e)
        return eq

    def path_basket(s, coins):
        px = (1 + R[coins].iloc[s: s + H]).cumprod().mean(axis=1).values   # buy-and-hold basket
        e0 = past[-1] * (1 - 2 * FEE * 0.95)                              # in and out
        return list(e0 * (1 + 0.95 * (px - 1)))

    pick = {
        "lock-in (adopted)": None,
        "all-in: top-momentum coin": lambda s: [mom.iloc[s].dropna().idxmax()],
        "all-in: most volatile coin": lambda s: [vol.iloc[s].dropna().idxmax()],
        "all-in: top-3 momentum": lambda s: list(mom.iloc[s].dropna().nlargest(3).index),
    }
    rng = np.random.default_rng(5)
    field = np.array(args.field) if args.field else None
    starts = range(0, len(port) - H, args.step)
    rows = []
    for label, f in pick.items():
        fin, comp, t20, t5, t1 = [], [], [], [], []
        for s in starts:
            fut = path_lockin(s) if f is None else path_basket(s, f(s))
            eq = np.concatenate([past, fut])
            r = eq[-1] - 1
            c = scores(eq, live_day)["daily"]
            fin.append(r)
            comp.append(c)
            if field is not None:
                m = np.add.reduceat(mkt[s: s + H], np.arange(0, H, 24))
                for _ in range(5):
                    Rf, Cf = competitor_paths(field, m, now_h / 24, now_h // 24 + 1, rng)
                    in20 = (Rf > r).sum() < 20
                    t20.append(in20)
                    better = (Cf[np.argsort(-Rf)[:19]] > c).sum() if in20 else 99
                    t5.append(better < 5)
                    t1.append(better == 0)
        fin = np.array(fin)
        row = {"plan": label, "P(R >= target)": f"{(fin >= args.target).mean():.2%}",
               "P(R >= +10%)": f"{(fin >= 0.10).mean():.1%}", "median R": f"{np.median(fin):+.2%}",
               "P(R < 0)": f"{(fin < 0).mean():.0%}", "P(R < -10%)": f"{(fin < -0.10).mean():.1%}",
               "median composite": f"{np.median(comp):.1f}"}
        if field is not None:
            row.update({"P(top20)": f"{np.mean(t20):.0%}", "P(top5 comp)": f"{np.mean(t5):.0%}",
                        "P(#1 comp)": f"{np.mean(t1):.0%}"})
        rows.append(row)
    pd.set_option("display.width", 250)
    print(f"banked {args.banked:+.2%}, {H} hours left, target {args.target:+.1%}, {len(starts)} stretches")
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
