"""Fast vectorised research backtester for cross-sectional strategies (2023 -> now).

Weights are decided at rebalance hour t from data <= t and held until the next
rebalance; costs = fee x |weight change|. Each variant is scored on every 14-day
window (stepped weekly) with the contest's composite metric, separately for the
in-sample (< 2025-06) and out-of-sample (>= 2025-06) periods.

Usage: python -m research.xs_backtest
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from bot.config import ROOT
from bot.metrics import summary
from research.signal_lab import SPLIT, features, load_panel


@dataclass(frozen=True)
class Variant:
    name: str
    signals: tuple = (("vol_72h", -1.0), ("max_ret_24h", -1.0), ("beta_btc", -1.0))
    n_side: int = 4                 # coins per side
    long_only: bool = False
    beta_neutral: bool = True
    target_daily_vol: float = 0.012
    max_gross: float = 0.95
    max_weight: float = 0.30
    rebalance_h: int = 24
    universe: int = 15              # most liquid coins by trailing 24h quote volume
    fee: float = 0.001              # per unit turnover (taker; conservative)
    long_bias: float = 0.0          # extra net long exposure (fraction of gross), e.g. 0.3
    long_max_rank: float = 1.0      # long only coins whose MAX-rank pct <= this (lottery filter)
    short_vol_rank: float = 1.0     # short only coins whose vol-rank pct <= this (avoid shorting wild coins)
    blend: tuple = ()               # names of variants to average (50/50) instead of own signals
    phase: int = 0                  # hour offset of the rebalance schedule (for tranching)
    tranches: int = 1               # average k phase-shifted copies (daily trading, slow turnover)


def zscore(row: pd.Series) -> pd.Series:
    s = row.dropna()
    if len(s) < 3 or s.std() == 0:
        return s * 0
    return ((s - s.mean()) / s.std()).clip(-3, 3)


def build_weights(v: Variant, panel, feats) -> pd.DataFrame:
    close, qv = panel
    logr = np.log(close).diff()
    vol24 = qv.rolling(24).sum()
    hours = close.index
    w_cur = pd.Series(dtype=float)
    weights = {}
    start = 800
    for i in range(start + v.phase, len(hours) - 1, v.rebalance_h):
        t = hours[i]
        liq = vol24.loc[t].dropna().sort_values(ascending=False)
        hist_ok = close.iloc[i - 720: i + 1].notna().all()
        uni = [c for c in liq.index if hist_ok.get(c, False)][: v.universe]
        if len(uni) < 2 * v.n_side + 2:
            continue
        score = pd.Series(0.0, index=uni)
        for name, sign in v.signals:
            score = score.add(sign * zscore(feats[name].loc[t, uni]), fill_value=0)
        score = score.dropna().sort_values(ascending=False)
        max_pct = feats["max_ret_24h"].loc[t, uni].rank(pct=True)
        vol_pct = feats["vol_72h"].loc[t, uni].rank(pct=True)
        long_pool = [c for c in score.index if max_pct.get(c, 0) <= v.long_max_rank]
        short_pool = [c for c in score.index[::-1] if vol_pct.get(c, 1) <= v.short_vol_rank]
        longs = long_pool[: v.n_side]
        shorts = [] if v.long_only else [c for c in short_pool if c not in longs][: v.n_side]
        if not longs:
            continue
        win = logr.iloc[i - 168: i + 1][longs + shorts]
        sd = win.std().replace(0, np.nan)
        w = pd.Series(0.0, index=longs + shorts)
        wl = (1 / sd[longs]); w[longs] = wl / wl.sum()
        if shorts:
            ws = (1 / sd[shorts]); w[shorts] = -(ws / ws.sum())
            if v.beta_neutral:
                beta = feats["beta_btc"].loc[t, longs + shorts].fillna(1.0).clip(0.2, 3)
                bl, bs = (w[longs] * beta[longs]).sum(), (-w[shorts] * beta[shorts]).sum()
                if bl > 0 and bs > 0:
                    w[shorts] *= bl / bs          # short leg beta = long leg beta
            if v.long_bias:
                w[longs] *= (1 + v.long_bias)
        w = w / w.abs().sum()
        cov = win.fillna(0).cov().values
        pv = float(np.sqrt(max(w.values @ cov @ w.values, 1e-12) * 24))
        gross = min(v.max_gross, v.target_daily_vol / pv)
        w = (w * gross).clip(-v.max_weight, v.max_weight)
        weights[t] = w
    # rows at rebalance times hold the FULL target (absent coins = 0) before forward-filling
    W = pd.DataFrame(weights).T.fillna(0.0).reindex(hours).ffill().fillna(0.0)
    return W.reindex(columns=close.columns, fill_value=0.0).fillna(0.0)


def evaluate(name: str, W: pd.DataFrame, close: pd.DataFrame, fee: float, start: int = 800) -> dict:
    rets = close.pct_change(fill_method=None)
    turnover = W.diff().abs().sum(axis=1).fillna(0.0)
    port = (W.shift(1) * rets.fillna(0)).sum(axis=1) - fee * turnover
    eq = (1 + port.iloc[start:]).cumprod() * 100_000
    rows = []
    t0 = eq.index[0]
    while t0 + pd.Timedelta(days=14) <= eq.index[-1]:
        seg = eq.loc[t0: t0 + pd.Timedelta(days=14)]
        rows.append({"start": t0, **summary(seg)})
        t0 += pd.Timedelta(days=7)
    win_df = pd.DataFrame(rows)
    out = {"variant": name}
    for label, part in (("IS", win_df[win_df.start < SPLIT]), ("OOS", win_df[win_df.start >= SPLIT])):
        out.update({f"{label}_med_ret%": 100 * part.total_return.median(),
                    f"{label}_mean_ret%": 100 * part.total_return.mean(),
                    f"{label}_p>0": (part.total_return > 0).mean(),
                    f"{label}_med_mdd%": 100 * part.max_drawdown.median(),
                    f"{label}_med_comp": part.composite.median()})
    full = summary(eq)
    out.update({"full_sharpe": full["sharpe"], "full_ret%": 100 * full["total_return"],
                "full_mdd%": 100 * full["max_drawdown"], "turnover/day": turnover.iloc[start:].mean() * 24})
    daily = port.iloc[start:].resample("1D").sum()
    for y, d in daily.groupby(daily.index.year):
        out[f"SR_{y}"] = d.mean() / d.std() * np.sqrt(365) if d.std() > 0 else 0.0
    return out


def build_tranched(v: Variant, panel, feats) -> pd.DataFrame:
    if v.tranches <= 1:
        return build_weights(v, panel, feats)
    step = v.rebalance_h // v.tranches
    parts = [build_weights(replace(v, phase=k * step), panel, feats) for k in range(v.tranches)]
    return sum(parts) / len(parts)


def run_variant(args) -> tuple:
    v, panel, feats = args
    W = build_tranched(v, panel, feats)
    return v.name, W, evaluate(v.name, W, panel[0], v.fee)


def variants() -> list:
    mom = (("mom_blend_168_336", 1.0),)
    t3 = dict(rebalance_h=72, tranches=3)
    out = []
    for vt in (0.012, 0.016, 0.020):
        out += [Variant(f"momF_vt{vt}", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, target_daily_vol=vt, **t3),
                Variant(f"lowriskLO_vt{vt}", long_only=True, target_daily_vol=vt, **t3)]
    out += [Variant("v1_momLS", signals=mom, **t3),
            Variant("v1_momLO", signals=mom, long_only=True, beta_neutral=False, **t3)]
    return out


BLENDS = [(f"NEW blend vt{vt}", f"momF_vt{vt}", f"lowriskLO_vt{vt}") for vt in (0.012, 0.016, 0.020)] + [
    ("V1 blend (live)", "v1_momLS", "v1_momLO"),
]


def main() -> None:
    close, qv, tq, fund, prem = load_panel()
    feats = features(close, qv, tq, fund, prem)
    keep = {k: feats[k] for k in ("vol_72h", "max_ret_24h", "beta_btc", "btc_catchup_4h",
                                  "mom_blend_168_336", "mom_336h_skip24")}
    print(f"panel: {close.shape[1]} coins {close.index[0].date()} -> {close.index[-1].date()}")
    jobs = [(v, (close, qv), keep) for v in variants()]
    with ProcessPoolExecutor() as pool:
        res = list(pool.map(run_variant, jobs))
    Ws = {name: W for name, W, _ in res}
    rows = [r for _, _, r in res]
    for label, a, b in BLENDS:
        Ws[label] = 0.5 * Ws[a] + 0.5 * Ws[b]
        rows.append(evaluate(label, Ws[label], close, 0.001))
    Ws["NEW+V1 50/50"] = 0.5 * Ws["NEW blend vt0.012"] + 0.5 * Ws["V1 blend (live)"]
    rows.append(evaluate("NEW+V1 50/50", Ws["NEW+V1 50/50"], close, 0.001))
    rets = close.pct_change(fill_method=None).fillna(0)
    print("\nLast 180 days / last 60 days (daily Sharpe, return %, max DD %):")
    for name in ["NEW blend vt0.012", "NEW blend vt0.016", "V1 blend (live)", "NEW+V1 50/50"]:
        W = Ws[name]
        port = (W.shift(1) * rets).sum(axis=1) - 0.001 * W.diff().abs().sum(axis=1).fillna(0)
        for days in (180, 60):
            seg = port.iloc[-24 * days:]
            d = seg.resample("1D").sum()
            eq = (1 + seg).cumprod()
            print(f"  {name:22s} {days:3d}d  SR {d.mean() / d.std() * np.sqrt(365):5.2f}  ret {100 * (eq.iloc[-1] - 1):6.2f}%  mdd {100 * (1 - eq / eq.cummax()).max():5.2f}%")
    df = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print(df.round(3).to_string(index=False))
    df.to_csv(ROOT / "data" / "xs_backtest_results.csv", index=False)


if __name__ == "__main__":
    main()
