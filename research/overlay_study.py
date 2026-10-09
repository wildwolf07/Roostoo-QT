"""Risk-overlay study: does the live overlay (drawdown brake, CPPI floor, 24h loss limit)
help the contest score, and which settings are robust?

Method: build the ensemble's hourly base returns (fees included) with the research
backtester, then for every 14-day window (stepped 3.5 days) replay the live overlay
path-dependently from a fresh $100k: exposure multiplier m_t is computed from the equity path
exactly like bot/risk/risk_manager.py and applied to the next hour's base return, with
the cost of changing exposure charged at the taker fee.

Usage: python -m research.overlay_study
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bot.config import ROOT, StrategyConfig
from bot.metrics import summary
from research.signal_lab import SPLIT, features, load_panel
from research.xs_backtest import Variant, build_tranched


@dataclass(frozen=True)
class Overlay:
    name: str
    dd_soft: float = 0.015
    dd_hard: float = 0.045
    dd_min: float = 0.25
    floor: float = 0.96
    cppi_m: float = 15.0
    day_limit: float = 0.015
    day_mult: float = 0.5
    enabled: bool = True


def ensemble_returns() -> tuple[pd.Series, pd.Series]:
    close, qv, tq, fund, prem = load_panel()
    feats = features(close, qv, tq, fund, prem)
    keep = {k: feats[k] for k in ("vol_72h", "max_ret_24h", "beta_btc", "mom_blend_168_336")}
    mom = (("mom_blend_168_336", 1.0),)
    t3 = dict(rebalance_h=72, tranches=3, universe=StrategyConfig().universe_size)   # live config
    sleeves = [
        Variant("mom_ls", signals=mom, **t3),
        Variant("mom_lo", signals=mom, long_only=True, beta_neutral=False, **t3),
        Variant("mom_f", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, **t3),
        Variant("lowrisk", long_only=True, **t3),
    ]
    W = sum(build_tranched(v, (close, qv), keep) for v in sleeves) / 4
    rets = close.pct_change(fill_method=None).fillna(0)
    turnover = W.diff().abs().sum(axis=1).fillna(0)
    base = (W.shift(1) * rets).sum(axis=1) - 0.001 * turnover
    gross = W.abs().sum(axis=1)
    return base.iloc[800:], gross.iloc[800:]


def replay(base: np.ndarray, gross: np.ndarray, ov: Overlay, fee: float = 0.001) -> np.ndarray:
    eq = np.empty(len(base) + 1)
    eq[0] = 1.0
    peak, m_prev = 1.0, 1.0
    for t, r in enumerate(base):
        e = eq[t]
        if ov.enabled:
            dd = 1 - e / peak
            if dd <= ov.dd_soft:
                ddm = 1.0
            elif dd >= ov.dd_hard:
                ddm = ov.dd_min
            else:
                ddm = 1 - (dd - ov.dd_soft) / (ov.dd_hard - ov.dd_soft) * (1 - ov.dd_min)
            cushion = max(0.0, (e - ov.floor) / e)
            g = gross[t] if gross[t] > 0 else 1.0
            cm = min(1.0, ov.cppi_m * cushion / g)
            prev = eq[max(0, t - 24)]
            dm = ov.day_mult if (e / prev - 1) <= -ov.day_limit else 1.0
            m = min(ddm, cm, dm)
        else:
            m = 1.0
        cost = fee * abs(m - m_prev) * gross[t]
        eq[t + 1] = e * (1 + m * r - cost)
        peak = max(peak, eq[t + 1])
        m_prev = m
    return eq


def study(base: pd.Series, gross: pd.Series, overlays: list, window_days: int = 14, step_h: int = 84) -> pd.DataFrame:
    H = window_days * 24
    b, g = base.values, gross.values
    rows = []
    for s in range(0, len(b) - H, step_h):
        t0 = base.index[s]
        idx = base.index[s: s + H + 1]
        for ov in overlays:
            eq = replay(b[s: s + H], g[s: s + H], ov)
            st = summary(pd.Series(eq * 100_000, index=idx))
            rows.append({"overlay": ov.name, "start": t0, "ret": st["total_return"], "mdd": st["max_drawdown"],
                         "sortino": st["sortino"], "sharpe": st["sharpe"], "calmar": st["calmar"],
                         "composite": st["composite"]})
    return pd.DataFrame(rows)


def overlays() -> list:
    out = [Overlay("none", enabled=False), Overlay("live_current")]
    for floor, m in itertools.product((0.94, 0.95, 0.96), (10.0, 15.0, 25.0)):
        out.append(Overlay(f"floor{floor}_m{m:g}", floor=floor, cppi_m=m))
    out += [Overlay("dd_only", floor=0.0, day_limit=1.0),
            Overlay("dd_loose", dd_soft=0.025, dd_hard=0.07, floor=0.0, day_limit=1.0),
            Overlay("cppi_only", dd_soft=1.0, dd_hard=1.1, day_limit=1.0)]
    return out


def main() -> None:
    base, gross = ensemble_returns()
    print(f"base series {base.index[0].date()} -> {base.index[-1].date()}, mean gross {gross.mean():.2f}")
    df = study(base, gross, overlays())
    df["period"] = np.where(df.start < pd.Timestamp(SPLIT, tz="UTC"), "IS", "OOS")
    agg = df.groupby(["overlay", "period"]).agg(
        med_ret=("ret", "median"), mean_ret=("ret", "mean"), p_pos=("ret", lambda x: (x > 0).mean()),
        p_ret_gt_2pct=("ret", lambda x: (x > 0.02).mean()), med_mdd=("mdd", "median"),
        p95_mdd=("mdd", lambda x: x.quantile(0.95)), med_comp=("composite", "median"),
        mean_comp_clip=("composite", lambda x: x.clip(-20, 50).mean())).reset_index()
    pd.set_option("display.width", 220)
    for period in ("IS", "OOS"):
        print(f"\n== {period} ==")
        print(agg[agg.period == period].drop(columns="period").sort_values("med_comp", ascending=False)
              .round(4).to_string(index=False))
    agg.to_csv(ROOT / "data" / "overlay_study.csv", index=False)


if __name__ == "__main__":
    main()
