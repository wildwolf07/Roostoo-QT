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


def apply_risk(weights: dict, risk_mult: float, cfg: StrategyConfig,
               blocked: frozenset = frozenset()) -> dict:
    """Scale base weights by the risk multiplier, then keep a small core position so the
    book always has something to manage (guarantees daily strategy-driven activity)."""
    out = {c: w * risk_mult for c, w in weights.items() if w * risk_mult != 0}
    total = sum(abs(v) for v in out.values())
    if total < cfg.min_gross and cfg.core_asset not in blocked:
        out[cfg.core_asset] = out.get(cfg.core_asset, 0.0) + (cfg.min_gross - total)
    return out
