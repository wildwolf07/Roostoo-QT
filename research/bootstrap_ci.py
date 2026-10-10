"""Stationary block bootstrap (Politis & Romano 1994) confidence intervals for the live ensemble's
daily performance 2023-2026: Sharpe, annual return, max drawdown, and P(Sharpe <= 0).

Usage: python -m research.bootstrap_ci
"""
from __future__ import annotations

import numpy as np

from research.overlay_study import ensemble_returns


def stationary_bootstrap(x: np.ndarray, n_boot: int = 3000, mean_block: int = 10, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = len(x)
    p = 1.0 / mean_block
    out = np.empty((n_boot, n))
    for b in range(n_boot):
        idx = np.empty(n, dtype=int)
        idx[0] = rng.integers(n)
        jumps = rng.random(n) < p
        starts = rng.integers(n, size=n)
        for t in range(1, n):
            idx[t] = starts[t] if jumps[t] else (idx[t - 1] + 1) % n
        out[b] = x[idx]
    return out


def main() -> None:
    base, _ = ensemble_returns()
    d = base.resample("1D").sum().values
    boot = stationary_bootstrap(d)
    sr = boot.mean(axis=1) / boot.std(axis=1) * np.sqrt(365)
    ann = boot.mean(axis=1) * 365
    eq = np.cumprod(1 + boot, axis=1)
    mdd = (1 - eq / np.maximum.accumulate(eq, axis=1)).max(axis=1)
    point_sr = d.mean() / d.std() * np.sqrt(365)
    print(f"daily returns n={len(d)}; point Sharpe {point_sr:.2f}")
    for name, v in (("Sharpe", sr), ("annual return (sum of daily)", ann), ("max drawdown", mdd)):
        lo, mid, hi = np.percentile(v, [2.5, 50, 97.5])
        print(f"{name:30s} median {mid:7.3f}  95% CI [{lo:7.3f}, {hi:7.3f}]")
    print(f"P(Sharpe <= 0) = {np.mean(sr <= 0):.3f}   P(Sharpe >= 1) = {np.mean(sr >= 1):.3f}")


if __name__ == "__main__":
    main()
