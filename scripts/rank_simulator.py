"""Rank simulator: probability of finishing top-3 / top-5 / top-20 in our region under each risk
plan, given the CURRENT returns of the competing teams.

Model (per simulated future = one historical stretch of `days` length, 2023-2026):
- us: our ensemble's realised return over the stretch at exposure k (fees included), compounded
  on our current return;
- each competitor i: current_i + beta_i * market_return_over_stretch + eps_i, where the market is
  the equal-weight crypto basket over the same stretch (so everyone shares the same market move),
  beta_i ~ U(0, beta_max) (most bots are long-biased) and eps_i ~ N(0, sigma_i^2 * days) with
  sigma_i drawn from [sig_lo, sig_hi] daily (unknown bot styles).
Because competitors' behaviour is unknown, results are reported for several field assumptions.

Usage (returns as decimals; ours first, then the other teams in our region):
  python -m scripts.rank_simulator --ours 0.010 --field 0.016 0.013 0.004 0.0 -0.01 ... --days 7
"""
from __future__ import annotations

import argparse

import numpy as np

from research.ablation import build
from research.robustness import _STATE, _init

PLANS = {
    "A  (1.0x)": ({"mom_ls": .25, "mom_lo": .25, "mom_f": .25, "lowrisk_lo": .25}, 1.0),
    "A- (0.75x)": ({"mom_ls": .25, "mom_lo": .25, "mom_f": .25, "lowrisk_lo": .25}, 0.75),
    "A+ (1.33x)": ({"mom_ls": .25, "mom_lo": .25, "mom_f": .25, "lowrisk_lo": .25}, 1.33),
    "B  (long, 1.33x)": ({"mom_lo": .5, "lowrisk_lo": .5}, 1.33),
}
FIELDS = {"calm field (0.5-1.5%/day, beta<=0.5)": (0.005, 0.015, 0.5),
          "mixed field (1-3%/day, beta<=1)": (0.01, 0.03, 1.0),
          "wild field (2-5%/day, beta<=1.5)": (0.02, 0.05, 1.5)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", type=float, required=True)
    ap.add_argument("--field", type=float, nargs="+", required=True, help="current returns of other teams in region")
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--sims-per-stretch", type=int, default=20)
    ap.add_argument("--elapsed-days", type=float, default=6.5, help="days the field has traded so far")
    ap.add_argument("--vol-floor", type=float, default=0.002, help="min daily vol for a calibrated competitor")
    args = ap.parse_args()
    _init()
    Ws = {n: build(n)[1] for n in ("mom_ls", "mom_lo", "mom_f", "lowrisk_lo")}
    close = _STATE["close"]
    rets = close.pct_change(fill_method=None).fillna(0)
    mkt = rets.mean(axis=1).iloc[800:].values
    H = int(args.days * 24)
    rng = np.random.default_rng(11)
    field = np.array(args.field)
    n = len(field)
    print(f"region: us at {args.ours:+.2%} + {n} other teams; current rank "
          f"{1 + int((field > args.ours).sum())}; horizon {args.days:g} days")
    # calibrated field: a team's realised displacement so far is its volatility proxy
    # (empirical Bayes: |return - median| / sqrt(elapsed days)), floored for inactive-looking teams
    disp = np.abs(field - np.median(field)) / np.sqrt(max(args.elapsed_days, 1.0))
    FIELDS_ALL = {"CALIBRATED from current returns": (None, None, 0.5)} | FIELDS
    for fname, (slo, shi, bmax) in FIELDS_ALL.items():
        print(f"\n{fname}")
        for label, (mix, k) in PLANS.items():
            W = sum(w * Ws[c] for c, w in mix.items())
            port = ((W.shift(1) * rets).sum(axis=1) - 0.001 * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:].values
            g = W.abs().sum(axis=1).iloc[800:].values
            ranks = []
            for s in range(0, len(port) - H, 24):
                kk = min(k, 0.95 / max(g[s: s + H].max(), 1e-9))
                ours = (1 + args.ours) * np.prod(1 + kk * port[s: s + H]) - 1
                m = np.prod(1 + mkt[s: s + H]) - 1
                for _ in range(args.sims_per_stretch):
                    beta = rng.uniform(0, bmax, n)
                    if slo is None:   # calibrated: inactive-looking teams (tiny displacement) carry ~no market beta
                        beta = beta * np.minimum(1.0, disp / 0.005)
                    sig = (np.maximum(disp * rng.uniform(0.8, 1.25, n), args.vol_floor) if slo is None
                           else rng.uniform(slo, shi, n))
                    others = field + beta * m + rng.normal(0, sig * np.sqrt(args.days))
                    ranks.append(1 + int((others > ours).sum()))
            r = np.array(ranks)
            print(f"  {label:18s} P(top 3) {np.mean(r <= 3):5.1%}  P(top 5) {np.mean(r <= 5):5.1%}  "
                  f"P(top 20) {np.mean(r <= 20):5.1%}  median rank {int(np.median(r))}")


if __name__ == "__main__":
    main()
