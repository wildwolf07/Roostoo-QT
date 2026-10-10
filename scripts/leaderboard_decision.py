"""Turn leaderboard numbers into a documented risk decision.

Inputs (from the Roostoo app leaderboard): our current contest return, the current return of the
team ranked #20 in our region, and the days left. The script estimates the probability that our
FINAL return beats the #20 team's final return under each plan, using every historical stretch of
the backtested ensemble for our remaining days. The #20 team's future drift is uncertain; we assume
it keeps a fraction of its current pace (default 0.5, i.e. it gives back some of its lead).

Runs on the research machine (needs data/research from `python -m research.download_full`).

Usage:
  python -m scripts.leaderboard_decision --ours 0.002 --rank20 0.035 --days-left 7 [--rank20-elapsed-days 6.5]
"""
from __future__ import annotations

import argparse

import numpy as np

from research.ablation import build
from research.robustness import _STATE, _init

PLANS = {
    "A  (live: equal sleeves, 1.0x)": ({"mom_ls": .25, "mom_lo": .25, "mom_f": .25, "lowrisk_lo": .25}, 1.0),
    "A+ (equal sleeves, 1.33x)": ({"mom_ls": .25, "mom_lo": .25, "mom_f": .25, "lowrisk_lo": .25}, 1.33),
    "B  (long mom + low-risk, 1.33x)": ({"mom_lo": .5, "lowrisk_lo": .5}, 1.33),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ours", type=float, required=True, help="our contest return so far, e.g. 0.002")
    ap.add_argument("--rank20", type=float, required=True, help="current return of rank #20, e.g. 0.035")
    ap.add_argument("--days-left", type=float, required=True)
    ap.add_argument("--rank20-elapsed-days", type=float, default=6.5,
                    help="days the #20 team has been trading (contest started Oct 4)")
    ap.add_argument("--rank20-keep", type=float, default=0.5,
                    help="fraction of #20's past daily pace it keeps going forward")
    args = ap.parse_args()

    pace = args.rank20 / max(args.rank20_elapsed_days, 0.5)
    cutoff_final = args.rank20 + args.rank20_keep * pace * args.days_left
    need = (1 + cutoff_final) / (1 + args.ours) - 1
    print(f"estimated final #20 return {cutoff_final:+.2%} -> we need {need:+.2%} over {args.days_left:g} days")

    _init()
    names = ("mom_ls", "mom_lo", "mom_f", "lowrisk_lo")
    Ws = {n: build(n)[1] for n in names}
    rets = _STATE["close"].pct_change(fill_method=None).fillna(0)
    H = int(args.days_left * 24)
    for label, (mix, k) in PLANS.items():
        W = sum(w * Ws[n] for n, w in mix.items())
        port = ((W.shift(1) * rets).sum(axis=1) - 0.001 * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:].values
        g = W.abs().sum(axis=1).iloc[800:].values
        outs = []
        for s in range(0, len(port) - H, 12):
            kk = min(k, 0.95 / max(g[s: s + H].max(), 1e-9))
            outs.append(np.prod(1 + kk * port[s: s + H]) - 1)
        outs = np.array(outs)
        print(f"{label:34s} P(clear cutoff) {(outs >= need).mean():5.1%} | median {np.median(outs):+.2%} | "
              f"P(loss > 3%) {(outs < -0.03).mean():5.1%} | P(loss > 5%) {(outs < -0.05).mean():5.1%}")
    print("rule: pick the plan with the highest P(clear cutoff) unless its gain over Plan A is under ~5 "
          "points; Plan B also lowers the median composite (2.11 -> 1.90).")


if __name__ == "__main__":
    main()
