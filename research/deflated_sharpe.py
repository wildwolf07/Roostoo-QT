"""Probabilistic and Deflated Sharpe Ratio (Bailey & Lopez de Prado 2012/2014) for the live
ensemble, accounting for every configuration we tried (all grids saved under data/*.csv).

Usage: python -m research.deflated_sharpe
"""
from __future__ import annotations

import glob
import math

import numpy as np
import pandas as pd

from bot.config import ROOT
from research.overlay_study import ensemble_returns

EULER = 0.5772156649


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def norm_ppf(p: float) -> float:
    lo, hi = -10.0, 10.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if norm_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def psr(sr: float, sr0: float, n: int, skew: float, kurt: float) -> float:
    """sr, sr0 in per-period units; kurt = raw kurtosis (normal = 3)."""
    denom = math.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr * sr, 1e-12))
    return norm_cdf((sr - sr0) * math.sqrt(n - 1) / denom)


def main() -> None:
    base, _ = ensemble_returns()
    daily = base.resample("1D").sum()
    n = len(daily)
    sr = daily.mean() / daily.std()
    skew = float(((daily - daily.mean()) ** 3).mean() / daily.std() ** 3)
    kurt = float(((daily - daily.mean()) ** 4).mean() / daily.std() ** 4)
    trials = []
    for f in glob.glob(str(ROOT / "data" / "*.csv")):
        df = pd.read_csv(f)
        if "full_sharpe" in df:
            trials += list(df["full_sharpe"].dropna())
    trials = np.array(trials)
    N = len(trials)
    var_sr_daily = (trials / math.sqrt(365)).var()
    sr0 = math.sqrt(var_sr_daily) * ((1 - EULER) * norm_ppf(1 - 1 / N) + EULER * norm_ppf(1 - 1 / (N * math.e)))
    print(f"live ensemble daily returns: n={n} days, annual Sharpe {sr * math.sqrt(365):.2f}, "
          f"skew {skew:.2f}, kurtosis {kurt:.2f}")
    print(f"trials recorded: N={N} (annual Sharpe range {trials.min():.2f}..{trials.max():.2f}, "
          f"std {trials.std():.2f})")
    print(f"PSR (P[true Sharpe > 0])                 = {psr(sr, 0.0, n, skew, kurt):.3f}")
    print(f"DSR (P[true Sharpe > best-of-{N} luck])   = {psr(sr, sr0, n, skew, kurt):.3f}  "
          f"(luck benchmark: annual Sharpe {sr0 * math.sqrt(365):.2f})")
    for n_trials in (80, 150):   # conservative: include unsaved early sweeps
        s0 = math.sqrt(var_sr_daily) * ((1 - EULER) * norm_ppf(1 - 1 / n_trials)
                                        + EULER * norm_ppf(1 - 1 / (n_trials * math.e)))
        print(f"DSR with N={n_trials} trials                = {psr(sr, s0, n, skew, kurt):.3f}  "
              f"(luck benchmark: annual Sharpe {s0 * math.sqrt(365):.2f})")


if __name__ == "__main__":
    main()
