"""Parity check: live ensemble code (bot/strategy/signals.py) == research backtester weights.

Usage: python -m research.parity_check
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import StrategyConfig
from bot.strategy.signals import _zscore, panel_features, sleeve_weights
from research.signal_lab import features, load_panel
from research.xs_backtest import Variant, build_weights


def main() -> None:
    close, qv, tq, fund, prem = load_panel()
    feats = features(close, qv, tq, fund, prem)
    cfg = StrategyConfig()
    mom = (("mom_blend_168_336", 1.0),)
    research = {
        "mom_ls": Variant("a", signals=mom, rebalance_h=24 * 30, universe=cfg.universe_size),
        "mom_lo": Variant("b", signals=mom, long_only=True, beta_neutral=False, rebalance_h=24 * 30,
                          universe=cfg.universe_size),
        "mom_filtered_ls": Variant("c", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, rebalance_h=24 * 30,
                                   universe=cfg.universe_size),
        "lowrisk_lo": Variant("d", long_only=True, rebalance_h=24 * 30, universe=cfg.universe_size),
    }
    Ws = {k: build_weights(v, (close, qv), feats) for k, v in research.items()}
    vol24 = qv.rolling(24).sum()
    rebal_times = [close.index[i] for i in range(800, len(close) - 1, 24 * 30)]
    rng = np.random.default_rng(7)
    worst = 0.0
    for t in rng.choice(rebal_times, size=8, replace=False):
        t = pd.Timestamp(t)
        i = close.index.get_loc(t)
        hist_ok = close.iloc[i - 720: i + 1].notna().all()
        uni = [c for c in vol24.loc[t].dropna().sort_values(ascending=False).index if hist_ok.get(c, False)][: cfg.universe_size]
        window = close.loc[:t, uni].iloc[-500:]
        f, r1 = panel_features(window)
        scores = {
            "mom_ls": _zscore(f["mom"][uni]), "mom_lo": _zscore(f["mom"][uni]),
            "mom_filtered_ls": _zscore(f["mom"][uni]),
            "lowrisk_lo": (-_zscore(f["vol"][uni])).add(-_zscore(f["max"][uni]), fill_value=0).add(-_zscore(f["beta"][uni]), fill_value=0),
        }
        kw = {"mom_ls": dict(long_only=False), "mom_lo": dict(long_only=True),
              "mom_filtered_ls": dict(long_only=False, long_max_rank=0.7, short_vol_rank=0.6),
              "lowrisk_lo": dict(long_only=True)}
        line = []
        for k in research:
            live = pd.Series(sleeve_weights(r1, f, scores[k], cfg, **kw[k]))
            res = Ws[k].loc[t]
            res = res[res.abs() > 1e-9]
            diff = live.reindex(res.index.union(live.index)).fillna(0) - res.reindex(res.index.union(live.index)).fillna(0)
            worst = max(worst, float(diff.abs().max()))
            line.append(f"{k}={diff.abs().max():.1e}")
        print(t.date(), "max |w_live - w_research| per sleeve:", ", ".join(line))
    print(f"\nPARITY {'OK' if worst < 1e-6 else 'FAILED'} (worst abs weight difference {worst:.2e})")


if __name__ == "__main__":
    main()
