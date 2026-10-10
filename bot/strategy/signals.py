"""Pure signal functions — no I/O. Shared verbatim by the live bot and the backtester.

Input is a DataFrame of hourly closes (index = time, columns = coins) that only
contains information available at decision time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from bot.config import StrategyConfig


@dataclass
class Regime:
    label: str          # RISK_ON | NEUTRAL | RISK_OFF
    multiplier: float   # scales gross exposure
    details: dict = field(default_factory=dict)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def market_regime(btc: pd.Series, cfg: StrategyConfig) -> Regime:
    """BTC trend + volatility state decides how much risk the whole book may take."""
    btc = btc.dropna()
    if len(btc) < cfg.regime_slow_ema + 24:
        return Regime("NEUTRAL", 0.5, {"reason": "insufficient history"})
    price = btc.iloc[-1]
    fast = ema(btc, cfg.regime_fast_ema).iloc[-1]
    slow = ema(btc, cfg.regime_slow_ema).iloc[-1]
    slow_prev = ema(btc, cfg.regime_slow_ema).iloc[-7]
    rets = np.log(btc).diff().dropna()
    vol_24h = rets.iloc[-24:].std()
    vol_base = rets.rolling(24).std().iloc[-336:].median()
    vol_spike = bool(vol_base and vol_24h > 2.0 * vol_base)

    if price > slow and fast > slow and slow >= slow_prev:
        label, mult = "RISK_ON", 1.0
    elif price < slow and fast < slow:
        label, mult = "RISK_OFF", 0.0
    else:
        label, mult = "NEUTRAL", 0.5
    if vol_spike:
        mult *= 0.5
    return Regime(label, mult, {
        "price": float(price), "ema_fast": float(fast), "ema_slow": float(slow),
        "vol_24h": float(vol_24h), "vol_base": float(vol_base or 0), "vol_spike": vol_spike,
    })


def momentum_scores(closes: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    """Average over lookbacks of the vol-normalised log return (a t-stat-like trend score)."""
    logp = np.log(closes)
    rets = logp.diff()
    vol = rets.iloc[-cfg.vol_lookback:].std()
    scores = {}
    for coin in closes.columns:
        s = logp[coin].dropna()
        v = vol.get(coin, np.nan)
        if len(s) <= max(cfg.mom_lookbacks) or not v or np.isnan(v):
            continue
        parts = [(s.iloc[-1] - s.iloc[-1 - L]) / (v * math.sqrt(L)) for L in cfg.mom_lookbacks]
        scores[coin] = float(np.mean(parts))
    return pd.Series(scores, dtype=float).sort_values(ascending=False)


def hourly_vol(closes: pd.DataFrame, lookback: int) -> pd.Series:
    return np.log(closes).diff().iloc[-lookback:].std()


def portfolio_daily_vol(closes: pd.DataFrame, weights: pd.Series, lookback: int = 168) -> float:
    rets = np.log(closes[weights.index]).diff().iloc[-lookback:].dropna()
    if len(rets) < 24:
        return float("nan")
    cov = rets.cov().values
    w = weights.values
    return float(math.sqrt(max(w @ cov @ w, 0.0) * 24))


def target_weights(closes: pd.DataFrame, cfg: StrategyConfig, regime: Regime,
                   blocked: frozenset = frozenset(), held: frozenset = frozenset()) -> tuple[dict, dict]:
    """Long-only *base* target weights (fraction of equity), before portfolio risk scaling.

    1. rank coins by momentum score; keep the top ``max_positions`` with positive score
    2. inverse-volatility weights, scaled so expected portfolio daily vol = target
    3. cap per asset and gross; multiply by the market-regime multiplier
    """
    scores = momentum_scores(closes, cfg)
    eligible = [c for c in scores.index if scores[c] > 0 and c not in blocked]
    picks = eligible[: cfg.max_positions]
    if cfg.hold_rank_buffer > 0:
        # hysteresis: keep held coins that are still near the top instead of churning them
        keep = [c for c in eligible[: cfg.max_positions + cfg.hold_rank_buffer] if c in held]
        fresh = [c for c in eligible if c not in keep][: max(0, cfg.max_positions - len(keep))]
        picks = keep + fresh
    weights: dict = {}
    port_vol = float("nan")

    if picks:
        vol = hourly_vol(closes[picks], cfg.vol_lookback).replace(0, np.nan).dropna()
        picks = list(vol.index)
    if picks:
        raw = (1.0 / vol) / (1.0 / vol).sum()
        port_vol = portfolio_daily_vol(closes, raw)
        if not port_vol or np.isnan(port_vol):
            gross = 0.5
        else:
            gross = min(cfg.max_gross, cfg.target_daily_vol / port_vol)
        w = (raw * gross).clip(upper=cfg.max_weight) * regime.multiplier
        weights = {c: float(x) for c, x in w.items() if x > 0}

    shorts: list = []
    if cfg.enable_shorts and regime.label == "RISK_OFF":
        losers = [c for c in reversed(scores.index)
                  if scores[c] < 0 and c not in blocked and c not in cfg.short_exclude]
        shorts = losers[: cfg.short_max_positions]
        if shorts:
            svol = hourly_vol(closes[shorts], cfg.vol_lookback).replace(0, np.nan).dropna()
            shorts = list(svol.index)
        if shorts:
            raw_s = (1.0 / svol) / (1.0 / svol).sum()
            pv = portfolio_daily_vol(closes, raw_s)
            sgross = cfg.short_max_gross if not pv or np.isnan(pv) else min(cfg.short_max_gross, cfg.target_daily_vol / pv)
            for c, x in (raw_s * sgross).clip(upper=cfg.max_weight).items():
                weights[c] = weights.get(c, 0.0) - float(x)

    diagnostics = {
        "shorts": shorts,
        "regime": regime.label, "regime_mult": regime.multiplier, "regime_details": regime.details,
        "scores": {c: round(float(s), 3) for c, s in scores.head(10).items()},
        "picks": picks, "portfolio_daily_vol": None if np.isnan(port_vol) else round(port_vol, 5),
        "blocked": sorted(blocked), "base_gross": round(sum(abs(v) for v in weights.values()), 4),
    }
    return weights, diagnostics


def xs_weights(closes: pd.DataFrame, cfg: StrategyConfig, regime: Regime,
               blocked: frozenset = frozenset()) -> tuple[dict, dict]:
    """Cross-sectional momentum: long the top ``max_positions`` scores, short the bottom
    ``short_max_positions`` (inverse-vol weighted, equal gross per side), scaled so the
    expected portfolio daily vol hits the target. Market exposure largely cancels, so
    returns come from relative strength rather than market direction."""
    scores = momentum_scores(closes, cfg)
    pool = [c for c in scores.index if c not in blocked]
    longs = pool[: cfg.max_positions]
    shorts = [c for c in reversed(pool) if c not in cfg.short_exclude and c not in longs][: cfg.short_max_positions]
    vol = hourly_vol(closes[longs + shorts], cfg.vol_lookback).replace(0, np.nan)
    w = pd.Series(0.0, index=longs + shorts)
    if longs:
        il = (1.0 / vol[longs]).fillna(0)
        w[longs] = il / il.sum() if il.sum() > 0 else 0
    if shorts:
        ish = (1.0 / vol[shorts]).fillna(0)
        w[shorts] = -(ish / ish.sum()) if ish.sum() > 0 else 0
    # optional directional tilt with the regime (0 = fully neutral)
    tilt = cfg.xs_net_bias * (1 if regime.label == "RISK_ON" else -1 if regime.label == "RISK_OFF" else 0)
    w[longs] *= (1 + tilt)
    w[shorts] *= (1 - tilt)
    w = w / max(w.abs().sum(), 1e-12)     # unit gross
    pv = portfolio_daily_vol(closes, w)
    gross = cfg.max_gross if not pv or np.isnan(pv) else min(cfg.max_gross, cfg.target_daily_vol / pv)
    w = (w * gross).clip(lower=-cfg.max_weight, upper=cfg.max_weight)
    weights = {c: float(x) for c, x in w.items() if abs(x) > 1e-6}
    diagnostics = {
        "style": "xs", "regime": regime.label, "regime_details": regime.details,
        "scores": {c: round(float(v), 3) for c, v in scores.items()},
        "longs": longs, "shorts": shorts,
        "portfolio_daily_vol": None if not pv or np.isnan(pv) else round(pv, 5),
        "blocked": sorted(blocked), "base_gross": round(sum(abs(v) for v in weights.values()), 4),
    }
    return weights, diagnostics


def _zscore(s: pd.Series) -> pd.Series:
    s = s.dropna()
    if len(s) < 3 or s.std() == 0:
        return s * 0
    return ((s - s.mean()) / s.std()).clip(-3, 3)


def panel_features(closes: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Latest-bar features used by the ensemble (identical formulas to research/signal_lab.py)."""
    logp = np.log(closes)
    r1 = logp.diff()
    vol = r1.rolling(72, min_periods=48).std()
    mom = ((logp - logp.shift(168)) / (vol * math.sqrt(168))
           + (logp - logp.shift(336)) / (vol * math.sqrt(336))) / 2
    maxr = r1.rolling(24).max()
    btc = r1["BTC"]
    beta = r1.rolling(336, min_periods=168).cov(btc).div(btc.rolling(336, min_periods=168).var(), axis=0)
    feats = {"mom": mom.iloc[-1], "vol": vol.iloc[-1], "max": maxr.iloc[-1], "beta": beta.iloc[-1]}
    return feats, r1


def sleeve_weights(r1: pd.DataFrame, feats: dict, score: pd.Series, cfg: StrategyConfig, long_only: bool,
                   beta_neutral: bool = True, long_max_rank: float = 1.0,
                   short_vol_rank: float = 1.0) -> dict:
    """One sleeve: pick longs/shorts from ``score``, inverse-vol weight each side, make the
    short leg's BTC-beta equal the long leg's (beta-neutral), scale to the daily vol target."""
    uni = list(score.index)
    score = score.dropna().sort_values(ascending=False)
    max_pct = feats["max"][uni].rank(pct=True)
    vol_pct = feats["vol"][uni].rank(pct=True)
    long_pool = [c for c in score.index if max_pct.get(c, 0) <= long_max_rank]
    short_pool = [c for c in score.index[::-1] if vol_pct.get(c, 1) <= short_vol_rank]
    n = cfg.ensemble_n
    longs = long_pool[:n]
    shorts = [] if long_only else [c for c in short_pool if c not in longs][:n]
    if not longs:
        return {}
    win = r1.iloc[-169:][longs + shorts]
    sd = win.std().replace(0, np.nan)
    w = pd.Series(0.0, index=longs + shorts)
    wl = 1 / sd[longs]
    w[longs] = wl / wl.sum()
    if shorts:
        ws = 1 / sd[shorts]
        w[shorts] = -(ws / ws.sum())
        if beta_neutral:
            beta = feats["beta"][longs + shorts].fillna(1.0).clip(0.2, 3)
            bl, bs = (w[longs] * beta[longs]).sum(), (-w[shorts] * beta[shorts]).sum()
            if bl > 0 and bs > 0:
                w[shorts] *= bl / bs
    w = w / w.abs().sum()
    cov = win.fillna(0).cov().values
    pv = float(np.sqrt(max(w.values @ cov @ w.values, 1e-12) * 24))
    gross = min(cfg.max_gross, cfg.target_daily_vol / pv)
    w = (w * gross).clip(-cfg.max_weight, cfg.max_weight)
    return {c: float(x) for c, x in w.items() if abs(x) > 1e-9 and not np.isnan(x)}


def ensemble_weights(closes: pd.DataFrame, cfg: StrategyConfig, blocked: frozenset = frozenset()) -> tuple[dict, dict]:
    """Equal-weight ensemble of four sleeves (evidence: research/xs_backtest.py, RESEARCH.md):
      1. cross-sectional momentum, long/short, beta-neutral
      2. long-only momentum
      3. filtered momentum: longs exclude lottery-like coins, shorts only calm coins
      4. low-risk long-only: low volatility, low MAX, low beta (lottery / BAB anomalies)
    """
    feats, r1 = panel_features(closes)
    uni = [c for c in closes.columns if c not in blocked and closes[c].iloc[-337:].notna().all()]
    mom = _zscore(feats["mom"][uni])
    lowrisk = (-_zscore(feats["vol"][uni])).add(-_zscore(feats["max"][uni]), fill_value=0) \
        .add(-_zscore(feats["beta"][uni]), fill_value=0)
    sleeves = {
        "mom_ls": sleeve_weights(r1, feats, mom, cfg, long_only=False),
        "mom_lo": sleeve_weights(r1, feats, mom, cfg, long_only=True),
        "mom_filtered_ls": sleeve_weights(r1, feats, mom, cfg, long_only=False,
                                          long_max_rank=cfg.lottery_max_rank, short_vol_rank=cfg.short_vol_rank),
        "lowrisk_lo": sleeve_weights(r1, feats, lowrisk, cfg, long_only=True),
    }
    acc: dict = {}
    for sw, w in zip(cfg.sleeve_weights, sleeves.values()):
        for c, x in w.items():
            acc[c] = acc.get(c, 0.0) + sw * x
    diag = {"style": "ensemble", "universe": uni, "sleeve_weights": list(cfg.sleeve_weights),
            "sleeves": {k: {c: round(x, 4) for c, x in v.items()} for k, v in sleeves.items()},
            "mom_z": {c: round(float(x), 2) for c, x in mom.sort_values(ascending=False).items()},
            "lowrisk_z": {c: round(float(x), 2) for c, x in lowrisk.sort_values(ascending=False).items()}}
    return {c: x for c, x in acc.items() if abs(x) > 1e-6}, diag


def _style_weights(closes: pd.DataFrame, cfg: StrategyConfig, regime: Regime,
                   blocked: frozenset, held: frozenset) -> tuple[dict, dict]:
    if cfg.style == "ensemble":
        return ensemble_weights(closes, cfg, blocked)
    if cfg.style == "xs":
        return xs_weights(closes, cfg, regime, blocked)
    trend_regime = regime if cfg.use_regime_gate else Regime(regime.label, 1.0, regime.details)
    if cfg.style == "blend":
        wt, dt = target_weights(closes, cfg, trend_regime, blocked, held)
        wx, dx = xs_weights(closes, cfg, regime, blocked)
        merged = {c: 0.5 * wt.get(c, 0.0) + 0.5 * wx.get(c, 0.0) for c in set(wt) | set(wx)}
        return {c: v for c, v in merged.items() if abs(v) > 1e-6}, {"style": "blend", "trend": dt, "xs": dx}
    return target_weights(closes, cfg, trend_regime, blocked, held)


def compute_base_weights(closes: pd.DataFrame, cfg: StrategyConfig, regime: Regime,
                         blocked: frozenset = frozenset(), held: frozenset = frozenset()) -> tuple[dict, dict]:
    """Single entry point for bot and backtester: style dispatch + tranche averaging.

    With ``tranches = k`` the target is the mean of the style weights computed on data
    ending now, ``spacing`` hours ago, ..., ``(k-1)*spacing`` hours ago. Rebalancing daily
    against this average is equivalent to holding k overlapping sub-portfolios that are
    each rebalanced every ``k*spacing`` hours."""
    k, gap = max(1, cfg.tranches), cfg.tranche_spacing_hours
    acc: dict = {}
    diags = []
    for i in range(k):
        window = closes if i == 0 else closes.iloc[: len(closes) - i * gap]
        w, d = _style_weights(window, cfg, regime, blocked, held)
        diags.append(d)
        for c, v in w.items():
            acc[c] = acc.get(c, 0.0) + v / k
    weights = {c: v for c, v in acc.items() if abs(v) > 1e-6}
    diag = dict(diags[0])
    diag.update(tranches=k, base_gross=round(sum(abs(v) for v in weights.values()), 4))
    return weights, diag


def apply_risk(weights: dict, risk_mult: float, cfg: StrategyConfig,
               blocked: frozenset = frozenset()) -> dict:
    """Scale base weights by the risk multiplier, then keep a small core position so the
    book always has something to manage (guarantees daily strategy-driven activity)."""
    out = {c: w * risk_mult for c, w in weights.items() if w * risk_mult != 0}
    total = sum(abs(v) for v in out.values())
    if total < cfg.min_gross and cfg.core_asset not in blocked:
        out[cfg.core_asset] = out.get(cfg.core_asset, 0.0) + (cfg.min_gross - total)
    return out
