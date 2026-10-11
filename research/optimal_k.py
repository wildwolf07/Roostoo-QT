"""Optimal endgame exposure: closed form and simulation.

Setting. The score is computed on the daily returns r_1..r_N of the whole contest window (N = 14).
Part of the window is already realised: sum S = sum(r_i), second moment Q = sum(r_i^2), downside
second moment Q- = sum(min(r_i, 0)^2), max drawdown M_p. The remaining n days earn k * x_t, where
x_t is the strategy's daily return at full size (mean mu, second moment s2 = sigma^2 + mu^2,
downside second moment d2 = E[min(x, 0)^2]) and k is the exposure multiplier we choose.

Closed form (ignoring the small mean correction inside the standard deviation):
  Sharpe(k)  ~ (S + k n mu) / sqrt(Q  + k^2 n s2)   ->  k*_Sharpe  = mu Q  / (S s2)
  Sortino(k) ~ (S + k n mu) / sqrt(Q- + k^2 n d2)   ->  k*_Sortino = mu Q- / (S d2)
Proof: d/dk of (S + kA)/sqrt(B + k^2 C) is zero when A B = S k C, i.e. k = A B / (S C) with
A = n mu, B = Q (or Q-), C = n s2 (or n d2). Read: k* is the Kelly leverage mu/s2 scaled by the
realised "variance per unit of profit" Q/S. A banked gain earned with little variance (small Q/S)
calls for very little further risk.
Calmar ~ g(S + k n mu) / max(M_p, k D_n), with D_n the future max drawdown at full size: raising k
adds return until k D_n starts to exceed the drawdown already on the books, so k*_Calmar ~ M_p / D_n.

The simulation then scores every fixed k (and the live rule) on all historical stretches with the
real path so far and the real field, under the four readings of the formula.

Usage: python -m research.optimal_k --path "<waypoints>" --now 2026-10-11T06:00 --k-now 0.34 --field ...
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from research.ablation import build
from research.endgame import (FEE, HOURS, LIVE, SLEEVES, START, TAPER_H, competitor_paths, k_fixed, k_lockin,
                              scores, waypoint_path)
from research.robustness import _STATE, _init


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--now", required=True)
    ap.add_argument("--k-now", type=float, default=1.0)
    ap.add_argument("--field", type=float, nargs="*", default=None)
    ap.add_argument("--field-mdd", type=float, nargs="*", default=None,
                    help="observed max drawdown so far for each --field team, same order (nan = unknown)")
    ap.add_argument("--field-beta", type=float, nargs="*", default=None,
                    help="known market exposure for each --field team, same order (nan = unknown)")
    ap.add_argument("--step", type=int, default=12)
    ap.add_argument("--recent-days", type=int, default=365, help="window for the strategy's daily moments")
    args = ap.parse_args()

    now = pd.Timestamp(args.now, tz="UTC").floor("1h")
    now_h = int((now - START) / pd.Timedelta(hours=1))
    H = HOURS - now_h
    to_rebal = (24 - now.hour) % 24
    live_day = int((LIVE.normalize() - START) / pd.Timedelta(days=1)) + 1
    past = waypoint_path(args.path, now_h)

    _init()
    W = sum(build(n)[1] for n in SLEEVES) / len(SLEEVES)
    rets = _STATE["close"].pct_change(fill_method=None).fillna(0)
    port_s = ((W.shift(1) * rets).sum(axis=1) - FEE * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:]
    port, gross = port_s.values, W.abs().sum(axis=1).iloc[800:].values
    mkt = rets.mean(axis=1).iloc[800:].values

    # ---- closed form
    day = past[::24]
    r_p = np.diff(day) / day[:-1]
    r_p = np.append(r_p, past[-1] / day[-1] - 1)          # today's partial day
    S, Q, Qm = r_p.sum(), (r_p ** 2).sum(), (np.minimum(r_p, 0) ** 2).sum()
    Mp = float((1 - past / np.maximum.accumulate(past)).max())
    x = (1 + port_s).resample("1D").prod().sub(1).iloc[-args.recent_days:]
    mu, s2, d2 = x.mean(), (x ** 2).mean(), (np.minimum(x, 0) ** 2).mean()
    n = H / 24
    D = []
    for s in range(0, len(port) - H, 24):
        e = np.cumprod(1 + port[s: s + H])
        D.append((1 - e / np.maximum.accumulate(e)).max())
    Dn = float(np.median(D))
    print(f"realised: S={S:+.4%} Q={Q:.2e} Q-={Qm:.2e} max DD {Mp:.2%}; strategy (last {args.recent_days}d): "
          f"mu={mu:+.3%}/day sigma={np.sqrt(s2 - mu ** 2):.3%} Kelly mu/s2={mu / s2:.1f}; median future DD at 1x {Dn:.2%}")
    print(f"closed form: k*_Sharpe = {mu * Q / (S * s2):.3f}   k*_Sortino = {mu * Qm / (S * d2):.3f}   "
          f"k*_Calmar ~ M_p/D_n = {Mp / Dn:.3f}")

    # ---- simulation over a grid
    grid = {f"fixed {k:.3f}x": k_fixed(k) for k in (0.0, 0.025, 0.05, 0.075, 0.10, 0.15, 0.25, 0.5, 1.0)}
    grid["live rule: 1x->0.10x by +0.25%"] = k_lockin(0.0025, 0.10)
    grid["old rule: 1x->0.15x by +1%"] = k_lockin(0.01, 0.15)
    field = np.array(args.field) if args.field else None
    mdd_obs = np.array(args.field_mdd) if args.field_mdd else None
    beta_obs = np.array(args.field_beta) if args.field_beta else None
    if mdd_obs is not None:
        assert field is not None and len(mdd_obs) == len(field), "--field-mdd must align with --field"
    rng = np.random.default_rng(3)
    rows = []
    for label, policy in grid.items():
        fin, comp, t5, t1 = [], {v: [] for v in ("daily", "hourly", "daily-active", "raw")}, [], []
        for s in range(0, len(port) - H, args.step):
            e, k, eq = past[-1], args.k_now, list(past)
            for t in range(H):
                if t == to_rebal or (t > to_rebal and (t - to_rebal) % 24 == 0):
                    nk = policy(e - 1.0) * (0.5 if now_h + t >= TAPER_H else 1.0)
                    e *= 1 - FEE * abs(nk - k) * gross[s + t]
                    k = nk
                e *= 1 + k * port[s + t]
                eq.append(e)
            eq = np.array(eq)
            fin.append(eq[-1] - 1)
            sc = scores(eq, live_day)
            for v in comp:
                comp[v].append(sc[v])
            if field is not None:
                m = np.add.reduceat(mkt[s: s + H], np.arange(0, H, 24))
                for _ in range(5):
                    R, C = competitor_paths(field, m, now_h / 24, now_h // 24 + 1, rng, mdd_obs, beta_obs)
                    in20 = (R > eq[-1] - 1).sum() < 20
                    better = (C[np.argsort(-R)[:19]] > sc["daily"]).sum() if in20 else 99
                    t5.append(better < 5)
                    t1.append(better == 0)
        fin = np.array(fin)
        row = {"policy": label, "median R": f"{np.median(fin):+.2%}", "P(R<0)": f"{(fin < 0).mean():.1%}"}
        for v, xs in comp.items():
            row[f"{v} p10/p50"] = f"{np.percentile(xs, 10):.1f}/{np.median(xs):.1f}"
        if field is not None:
            row["P(top5)"] = f"{np.mean(t5):.1%}"
            row["P(#1)"] = f"{np.mean(t1):.1%}"
        rows.append(row)
    pd.set_option("display.width", 300)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
