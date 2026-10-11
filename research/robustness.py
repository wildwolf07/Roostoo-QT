"""Robustness grid for the 4-sleeve ensemble: vary one parameter at a time around the live
configuration and check that performance is a plateau, not a sharp peak.

Usage: python -m research.robustness
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from bot.config import ROOT, StrategyConfig
from research.signal_lab import features, load_panel
from research.xs_backtest import Variant, build_tranched, evaluate

_STATE: dict = {}


def _init():
    close, qv, tq, fund, prem = load_panel()
    f = features(close, qv, tq, fund, prem)
    f["mom_72_168_336"] = (f["mom_72h"] + f["mom_168h"] + f["mom_336h"]) / 3
    f["mom_336_720"] = (f["mom_336h"] + f["mom_720h"]) / 2
    f["mom_168_only"] = f["mom_168h"]
    keep = ("vol_72h", "max_ret_24h", "beta_btc", "mom_blend_168_336", "mom_72_168_336", "mom_336_720", "mom_168_only",
            "res_mom_168_336")
    _STATE.update(close=close, qv=qv, feats={k: f[k] for k in keep})


def ensemble(cfg: dict) -> pd.DataFrame:
    close, qv, feats = _STATE["close"], _STATE["qv"], _STATE["feats"]
    mom = ((cfg.get("mom", "mom_blend_168_336"), 1.0),)
    mom_ls = ((cfg.get("mom_ls", cfg.get("mom", "mom_blend_168_336")), 1.0),)
    common = dict(rebalance_h=cfg.get("rb", 72), tranches=3, n_side=cfg.get("n", 4),
                  universe=cfg.get("uni", StrategyConfig().universe_size), target_daily_vol=cfg.get("vt", 0.012))
    lr, sv = cfg.get("lmr", 0.7), cfg.get("svr", 0.6)
    sleeves = [
        Variant("a", signals=mom_ls, **common),
        Variant("b", signals=mom, long_only=True, beta_neutral=False, **common),
        Variant("c", signals=mom_ls, long_max_rank=lr, short_vol_rank=sv, **common),
        Variant("d", long_only=True, **common),
    ]
    ws = cfg.get("weights", (0.25, 0.25, 0.25, 0.25))
    return sum(w * build_tranched(v, (close, qv), feats) for w, v in zip(ws, sleeves))


def run(item):
    name, cfg = item
    if not _STATE:
        _init()
    W = ensemble(cfg)
    return evaluate(name, W, _STATE["close"], 0.001)


def grid() -> list:
    base = {}
    g = [("BASE (live)", base)]
    for n in (3, 5):
        g.append((f"n={n}", {"n": n}))
    for mom in ("mom_72_168_336", "mom_336_720", "mom_168_only"):
        g.append((f"mom={mom}", {"mom": mom}))
    for rb in (48, 96):
        g.append((f"rebalance={rb}h", {"rb": rb}))
    for uni in (20, 29):
        g.append((f"universe={uni}", {"uni": uni}))
    for lmr, svr in ((0.6, 0.5), (0.8, 0.7)):
        g.append((f"filters={lmr}/{svr}", {"lmr": lmr, "svr": svr}))
    g.append(("weights=momentum-heavy", {"weights": (0.3, 0.3, 0.2, 0.2)}))
    g.append(("weights=lowrisk-heavy", {"weights": (0.2, 0.2, 0.25, 0.35)}))
    g.append(("vol_target=0.016", {"vt": 0.016}))
    return g


def main() -> None:
    import os
    g = grid()
    if os.environ.get("GRID") == "resmom":
        g = [("BASE (live)", {}), ("residual mom in L/S sleeves", {"mom_ls": "res_mom_168_336"}),
             ("residual mom in all mom sleeves", {"mom": "res_mom_168_336"})]
    with ProcessPoolExecutor(initializer=_init) as pool:
        rows = list(pool.map(run, g))
    df = pd.DataFrame(rows)
    cols = ["variant", "IS_med_comp", "OOS_med_comp", "IS_p>0", "OOS_p>0", "IS_med_mdd%", "OOS_med_mdd%",
            "full_sharpe", "full_ret%", "full_mdd%", "turnover/day", "SR_2023", "SR_2024", "SR_2025", "SR_2026"]
    pd.set_option("display.width", 250)
    print(df[cols].round(3).to_string(index=False))
    df.to_csv(ROOT / "data" / "robustness.csv", index=False)
    sr = df["full_sharpe"]
    print(f"\nfull-period Sharpe across {len(df)} configs: min {sr.min():.2f}, median {sr.median():.2f}, max {sr.max():.2f}; "
          f"base rank {int((sr > sr.iloc[0]).sum()) + 1}/{len(df)}")


if __name__ == "__main__":
    main()
