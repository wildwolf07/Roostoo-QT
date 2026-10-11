"""Endgame study: how much risk to run for the rest of the contest, given the P&L already banked.

Finalists are picked in stages: the top 20 of each region by return go through, those are ranked by
0.4 Sortino + 0.3 Sharpe + 0.3 Calmar over the contest window, and the top 5 per region (after code
review) are the finalists. The three ratios are scale-free only while nothing is banked. Once a gain B
is in the numerator, every further unit of risk adds more to the denominators (volatility, downside
deviation, max drawdown) than to the numerators, so less exposure means a higher score. The price is
return: if the region's #20 ends above our return, we are out before the score is even computed.

This study measures both sides on every historical stretch of the live ensemble (fees included):
our final return, our composite under four plausible versions of the organisers' formula (it is not
published), and, if a field of competitors' returns is given, P(top 20) and P(top 5 by composite).

Usage:
  python -m research.endgame --banked 0.010 --now 2026-10-10T17:00 [--mdd-so-far 0.0011]
                             [--field 0.016 0.013 ...]   # other teams in our region, decimals
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from research.ablation import build
from research.robustness import _STATE, _init

START = pd.Timestamp("2026-10-04", tz="UTC")
LIVE = pd.Timestamp("2026-10-09 22:00", tz="UTC")     # our first hour in the market
HOURS = 14 * 24                                        # contest window Oct 4 00:00 -> Oct 18 00:00
TAPER_H = 13 * 24                                      # live taper (0.5x) acts from the Oct 17 rebalance
FEE = 0.001
SLEEVES = ("mom_ls", "mom_lo", "mom_f", "lowrisk_lo")


def k_fixed(k):
    return lambda banked: k


def k_lockin(full_at: float, k_min: float):
    """Exposure falls linearly from 1 (nothing banked or a loss) to k_min once `full_at` is banked."""
    return lambda banked: 1.0 - (1.0 - k_min) * float(np.clip(banked / full_at, 0.0, 1.0))


POLICIES = {
    "A   live, 1.0x": k_fixed(1.0),
    "A+  1.33x": k_fixed(1.33),
    "F75 0.75x": k_fixed(0.75),
    "F50 0.50x": k_fixed(0.50),
    "F35 0.35x": k_fixed(0.35),
    "F25 0.25x": k_fixed(0.25),
    "F15 0.15x": k_fixed(0.15),
    "F10 0.10x": k_fixed(0.10),
    "F05 0.05x": k_fixed(0.05),
    "L1  lock-in 1x->0.35x by +1%": k_lockin(0.01, 0.35),
    "L2  lock-in 1x->0.35x by +2%": k_lockin(0.02, 0.35),
    "L3  lock-in 1x->0.25x by +1.5%": k_lockin(0.015, 0.25),
    "L4  lock-in 1x->0.25x by +1%": k_lockin(0.01, 0.25),
    "L5  lock-in 1x->0.15x by +1%": k_lockin(0.01, 0.15),
    "L6  lock-in 1x->0.10x by +1%": k_lockin(0.01, 0.10),
    "L7  lock-in 1x->0.15x by +0.25%": k_lockin(0.0025, 0.15),
    "L8  lock-in 1x->0.10x by +0.25%": k_lockin(0.0025, 0.10),
}


def scores(eq: np.ndarray, live_day: int) -> dict:
    """Composite under four readings of the formula. `eq` is the hourly equity over the window
    (HOURS + 1 points, starting at 1.0)."""
    out = {}
    R = eq[-1] / eq[0] - 1
    mdd_h = float((1 - eq / np.maximum.accumulate(eq)).max())
    day_eq = eq[::24]
    for name, r, ppy, mdd, calmar_kind, days in (
        ("daily", np.diff(day_eq) / day_eq[:-1], 365, mdd_h, "compound", 14.0),
        ("hourly", np.diff(eq) / eq[:-1], 8760, mdd_h, "compound", 14.0),
        ("daily-active", np.diff(day_eq[live_day:]) / day_eq[live_day:-1], 365, mdd_h, "simple", 14.0 - live_day),
        ("raw", np.diff(day_eq) / day_eq[:-1], 1, mdd_h, "total", 14.0),
    ):
        mean, sd = r.mean(), r.std(ddof=1)
        down = max(np.sqrt((np.minimum(r, 0) ** 2).mean()), 1e-6)
        sharpe = mean / sd * np.sqrt(ppy) if sd > 0 else 0.0
        sortino = mean / down * np.sqrt(ppy)
        m = max(mdd, 1e-5)
        if calmar_kind == "compound":
            calmar = ((1 + R) ** (365 / days) - 1) / m
        elif calmar_kind == "simple":
            calmar = mean * 365 / m
        else:
            calmar = R / m
        out[name] = 0.4 * sortino + 0.3 * sharpe + 0.3 * calmar
    return out


def realised_path(banked: float, now_h: int, mdd: float) -> np.ndarray:
    """Hourly equity from Oct 4 to now: flat cash until we went live, then a ramp to the banked
    return with one dip of the observed size (only the max drawdown and the end point matter)."""
    live_h = int((LIVE - START) / pd.Timedelta(hours=1))
    eq = np.ones(now_h + 1)
    n = now_h - live_h
    ramp = 1 + banked * np.linspace(0, 1, n + 1) ** 0.5
    mid = n // 2
    ramp[mid:] *= np.where(np.arange(n + 1 - mid) == 0, 1 - mdd, 1.0)
    eq[live_h:] = ramp
    return eq


def waypoint_path(points: str, now_h: int) -> np.ndarray:
    """Hourly equity from Oct 4 to now from observed waypoints "ISO=return,ISO=return,..."
    (contest return at each time, linearly interpolated; flat before the first waypoint)."""
    ts, vals = [], []
    for item in points.split(","):
        t, v = item.split("=")
        ts.append((pd.Timestamp(t, tz="UTC") - START) / pd.Timedelta(hours=1))
        vals.append(float(v))
    return 1 + np.interp(np.arange(now_h + 1), ts, vals, left=0.0, right=vals[-1])


def competitor_paths(field: np.ndarray, mkt_daily: np.ndarray, elapsed: float, now_day: int,
                     rng: np.random.Generator, mdd_obs: np.ndarray | None = None,
                     beta_obs: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Daily equity paths for the other teams: the realised part is a random path that ends at each
    team's current return; the future is beta * market + noise. Volatility is calibrated from how far
    each team has moved from the median so far (floored), beta is lower for teams that barely move.
    Where a team's max drawdown so far is observed (mdd_obs, NaN = unknown), it sets the volatility
    (E[max DD] ~ 1.25 sigma sqrt(T) for a driftless walk, Magdon-Ismail & Atiya 2004) and is a floor
    for the team's final max drawdown. Where a team's market exposure is known from its public portfolio
    (beta_obs, e.g. 0.30 for a 30% long-only crypto book; NaN = unknown) it replaces the random beta."""
    n = len(field)
    disp = np.abs(field - np.median(field)) / np.sqrt(max(elapsed, 1.0))
    if mdd_obs is not None:
        known = ~np.isnan(mdd_obs)
        disp = np.where(known, np.nan_to_num(mdd_obs) / (1.25 * np.sqrt(max(elapsed, 1.0))), disp)
    sig = np.maximum(disp * rng.uniform(0.8, 1.25, n), 0.002)
    beta = rng.uniform(0, 0.5, n) * np.minimum(1.0, disp / 0.005)
    if beta_obs is not None:
        beta = np.where(np.isnan(beta_obs), beta, np.nan_to_num(beta_obs))
    past = rng.normal(0, 1, (n, now_day)) * sig[:, None]
    past = past - past.mean(axis=1, keepdims=True) + (np.log1p(field) / now_day)[:, None]
    fut_days = 14 - now_day
    fut = beta[:, None] * mkt_daily[None, :fut_days] + rng.normal(0, 1, (n, fut_days)) * sig[:, None]
    logs = np.concatenate([np.zeros((n, 1)), np.cumsum(np.concatenate([past, np.log1p(fut)], axis=1), axis=1)], axis=1)
    eq = np.exp(logs)
    R = eq[:, -1] - 1
    mdd = (1 - eq / np.maximum.accumulate(eq, axis=1)).max(axis=1)
    if mdd_obs is not None:
        mdd = np.maximum(mdd, np.nan_to_num(mdd_obs))
    # every team starts at its peak ($100k), so a team now below water has already drawn down at least
    # that much: max DD >= max(0, -return so far)
    mdd = np.maximum(mdd, np.maximum(0.0, -field))
    r = np.diff(eq, axis=1) / eq[:, :-1]
    mean, sd = r.mean(axis=1), r.std(axis=1, ddof=1)
    down = np.maximum(np.sqrt((np.minimum(r, 0) ** 2).mean(axis=1)), 1e-6)
    comp = (0.4 * mean / down * np.sqrt(365) + 0.3 * mean / sd * np.sqrt(365)
            + 0.3 * ((1 + R) ** (365 / 14) - 1) / np.maximum(mdd, 1e-5))
    return R, comp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--banked", type=float, required=True, help="our contest return so far, e.g. 0.010")
    ap.add_argument("--now", default="2026-10-10T17:00", help="UTC hour of the observation")
    ap.add_argument("--mdd-so-far", type=float, default=0.0011)
    ap.add_argument("--field", type=float, nargs="*", default=None, help="current returns of other teams in region")
    ap.add_argument("--step", type=int, default=6, help="hours between historical start points")
    ap.add_argument("--k-now", type=float, default=1.0, help="exposure multiplier live until the next rebalance")
    ap.add_argument("--path", default=None, help='observed waypoints "ISO=return,..." (overrides --banked/--mdd-so-far shape)')
    args = ap.parse_args()

    now = pd.Timestamp(args.now, tz="UTC").floor("1h")
    now_h = int((now - START) / pd.Timedelta(hours=1))
    to_rebal = (24 - now.hour) % 24
    live_day = int((LIVE.normalize() - START) / pd.Timedelta(days=1)) + 1     # first full live day
    _init()
    Ws = {n: build(n)[1] for n in SLEEVES}
    W = sum(Ws.values()) / len(Ws)
    rets = _STATE["close"].pct_change(fill_method=None).fillna(0)
    port = ((W.shift(1) * rets).sum(axis=1) - FEE * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:].values
    gross = W.abs().sum(axis=1).iloc[800:].values
    mkt = rets.mean(axis=1).iloc[800:].values
    past = waypoint_path(args.path, now_h) if args.path else realised_path(args.banked, now_h, args.mdd_so_far)
    H = HOURS - now_h
    starts = range(0, len(port) - H, args.step)
    print(f"now {now:%Y-%m-%d %H:%M} UTC, banked {args.banked:+.2%}, {H} hours left, next rebalance in {to_rebal}h; "
          f"{len(starts)} historical stretches")

    rng = np.random.default_rng(7)
    field = np.array(args.field) if args.field else None
    rows, comp_q = [], {}
    for label, policy in POLICIES.items():
        finals, comps, top20, top5, top1 = [], {v: [] for v in ("daily", "hourly", "daily-active", "raw")}, [], [], []
        for s in starts:
            eq = list(past)
            e, k = eq[-1], args.k_now
            for t in range(H):
                h = now_h + t
                if t == to_rebal or (t > to_rebal and (t - to_rebal) % 24 == 0):
                    new_k = policy(e - 1.0) * (0.5 if h >= TAPER_H else 1.0)
                    e *= 1 - FEE * abs(new_k - k) * gross[s + t]
                    k = new_k
                e *= 1 + k * port[s + t]
                eq.append(e)
            eq = np.array(eq)
            finals.append(eq[-1] - 1)
            sc = scores(eq, live_day)
            for v in comps:
                comps[v].append(sc[v])
            if field is not None:
                m = np.add.reduceat(mkt[s: s + H], np.arange(0, H, 24))
                for _ in range(5):
                    R, C = competitor_paths(field, m, now_h / 24, now_h // 24 + 1, rng)
                    above = R > eq[-1] - 1
                    in20 = above.sum() < 20
                    top20.append(in20)
                    better = (C[np.argsort(-R)[:19]] > sc["daily"]).sum() if in20 else 99
                    top5.append(better < 5)
                    top1.append(better == 0)
        f = np.array(finals)
        row = {"policy": label, "median R": f"{np.median(f):+.2%}", "p5 R": f"{np.percentile(f, 5):+.2%}",
               "P(R<0)": f"{(f < 0).mean():.0%}", "P(R<0.5%)": f"{(f < 0.005).mean():.0%}",
               "P(R>2%)": f"{(f > 0.02).mean():.0%}"}
        for v, xs in comps.items():
            row[f"{v} p25/p50"] = f"{np.percentile(xs, 25):.1f} / {np.median(xs):.1f}"
        if field is not None:
            row["P(top20)"] = f"{np.mean(top20):.0%}"
            row["P(top5 comp)"] = f"{np.mean(top5):.0%}"
            row["P(#1 comp)"] = f"{np.mean(top1):.0%}"
        rows.append(row)
        comp_q[label] = np.percentile(comps["daily"], np.arange(5, 100, 5))
    pd.set_option("display.width", 300)
    print(pd.DataFrame(rows).to_string(index=False))
    base = comp_q["A   live, 1.0x"]
    print("\nstochastic dominance vs A (daily formula): share of the 5..95% quantiles where the policy scores higher")
    for label, q in comp_q.items():
        print(f"  {label:32s} {(q > base).mean():.0%}")


if __name__ == "__main__":
    main()
