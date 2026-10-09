"""Ablation: contribution of each ensemble sleeve, plus a candidate 5th sleeve.

Usage: python -m research.ablation
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from bot.config import ROOT, StrategyConfig
from research.robustness import _STATE, _init
from research.xs_backtest import Variant, build_tranched, evaluate

UNI = StrategyConfig().universe_size


def sleeves() -> dict:
    mom = (("mom_blend_168_336", 1.0),)
    c = dict(rebalance_h=72, tranches=3, n_side=4, universe=UNI)
    return {
        "mom_ls": Variant("mom_ls", signals=mom, **c),
        "mom_lo": Variant("mom_lo", signals=mom, long_only=True, beta_neutral=False, **c),
        "mom_f": Variant("mom_f", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, **c),
        "lowrisk_lo": Variant("lowrisk_lo", long_only=True, **c),
        "lowrisk_ls_falling": Variant("lowrisk_ls_falling", short_needs_neg_mom=True, **c),
    }


def build(name: str):
    if not _STATE:
        _init()
    return name, build_tranched(sleeves()[name], (_STATE["close"], _STATE["qv"]), _STATE["feats"])


def main() -> None:
    names = list(sleeves())
    with ProcessPoolExecutor(initializer=_init) as pool:
        Ws = dict(pool.map(build, names))
    _init()
    close = _STATE["close"]
    base4 = ["mom_ls", "mom_lo", "mom_f", "lowrisk_lo"]
    combos = {"ALL 4 (live)": base4}
    for drop in base4:
        combos[f"without {drop}"] = [s for s in base4 if s != drop]
    combos["ALL 4 + lowrisk_ls_falling"] = base4 + ["lowrisk_ls_falling"]
    for s in names:
        combos[f"only {s}"] = [s]
    rows = []
    for label, members in combos.items():
        W = sum(Ws[m] for m in members) / len(members)
        rows.append(evaluate(label, W, close, 0.001))
    df = pd.DataFrame(rows)
    cols = ["variant", "IS_med_comp", "OOS_med_comp", "OOS_p>0", "OOS_med_mdd%", "full_sharpe", "full_ret%",
            "full_mdd%", "turnover/day", "SR_2023", "SR_2024", "SR_2025", "SR_2026"]
    pd.set_option("display.width", 250)
    print(f"universe {UNI}")
    print(df[cols].round(3).to_string(index=False))
    # sleeve return correlations (daily)
    rets = close.pct_change(fill_method=None).fillna(0)
    daily = pd.DataFrame({m: ((Ws[m].shift(1) * rets).sum(axis=1)).resample("1D").sum() for m in names}).iloc[40:]
    print("\nsleeve daily-return correlations:\n", daily.corr().round(2).to_string())
    df.to_csv(ROOT / "data" / "ablation.csv", index=False)


if __name__ == "__main__":
    main()
