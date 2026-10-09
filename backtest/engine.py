"""Hourly backtester that calls the *same* strategy and risk code as the live bot.

Simplifications (documented in the README):
- decisions and fills at the hourly close; fills pay ``fee`` (default = taker 0.1%)
  plus ``slippage`` per side
- trailing stops are checked on hourly closes (live bot checks every minute)
- universe = top-N whitelisted coins by trailing 24h quote volume

Usage: python -m backtest.engine [--start 2025-06-01] [--end 2026-10-09] [--windows]
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import timezone

import numpy as np
import pandas as pd

from bot.config import ROOT, RiskConfig, StrategyConfig
from bot.metrics import summary
from bot.risk.risk_manager import RiskManager
from bot.strategy.signals import apply_risk, hourly_vol, market_regime, target_weights

DATA = ROOT / "data" / "klines"


def load_data(coins) -> tuple[pd.DataFrame, pd.DataFrame]:
    closes, vols = {}, {}
    for c in coins:
        path = DATA / f"{c}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        closes[c] = df["close"]
        vols[c] = df["quote_volume"]
    closes_df = pd.DataFrame(closes).sort_index().ffill(limit=3)
    return closes_df, pd.DataFrame(vols).sort_index().reindex(closes_df.index)


def run(start: str, end: str, scfg: StrategyConfig = StrategyConfig(), rcfg: RiskConfig = RiskConfig(),
        fee: float = 0.001, slippage: float = 0.0002, deadband: float = 0.02, min_order: float = 200.0,
        closes: pd.DataFrame | None = None, vols: pd.DataFrame | None = None) -> tuple[pd.Series, dict]:
    if closes is None:
        closes, vols = load_data(scfg.whitelist)
    vol24 = vols.rolling(24).sum()
    rcfg = replace(rcfg, taper_start=pd.Timestamp("2100-01-01", tz="UTC").to_pydatetime())
    risk = RiskManager(rcfg)
    idx = closes.loc[start:end].index
    cash, qty = rcfg.initial_equity, {}
    equity_curve, turnover, fees_paid, trades = [], 0.0, 0.0, 0
    warm = scfg.history_bars

    for t in idx:
        pos = closes.index.get_loc(t)
        if pos < warm:
            continue
        px = closes.iloc[pos]
        values = {c: q * px[c] for c, q in qty.items() if not np.isnan(px.get(c, np.nan))}
        if len(values) < len(qty):  # a held coin has no price this hour: carry last equity
            continue
        equity = cash + sum(values.values())
        now = t.to_pydatetime().replace(tzinfo=timezone.utc)
        risk.update_equity(equity, now)

        rebalance_now = t.hour % scfg.rebalance_hours == 0
        # trailing stops on hourly closes
        stops = risk.check_stops(values, px.to_dict(), now, min_order)
        target_override = {}
        for c in stops:
            target_override[c] = 0.0
            risk.start_cooldown(c, now)

        window = closes.iloc[pos - warm + 1: pos + 1]
        ranked = vol24.iloc[pos].dropna().sort_values(ascending=False)
        universe = [c for c in ranked.index if c in window and window[c].notna().all()][: scfg.universe_size]
        if "BTC" not in universe:
            universe.append("BTC")
        win = window[universe]
        dvol = hourly_vol(win, scfg.vol_lookback) * np.sqrt(24)
        risk.state.asset_daily_vol.update({c: float(v) for c, v in dvol.dropna().items()})

        regime = market_regime(win["BTC"], scfg)
        blocked = risk.blocked(now)
        base, _ = target_weights(win, scfg, regime, blocked)
        mult, _ = risk.exposure_multiplier(equity, now, sum(base.values()))
        targets = apply_risk(base, mult, scfg, blocked)
        if not rebalance_now:
            # between scheduled rebalances only stops act: hold everything else
            targets = {c: values.get(c, 0.0) / equity for c in qty}
        targets.update(target_override)

        # trade toward targets (sells first)
        for side in ("SELL", "BUY"):
            for c in sorted(set(targets) | set(qty)):
                p = px.get(c, np.nan)
                if np.isnan(p) or p <= 0:
                    continue
                cur = qty.get(c, 0.0) * p
                diff = targets.get(c, 0.0) * equity - cur
                full_exit = targets.get(c, 0.0) <= 0 and cur >= min_order
                if not full_exit and abs(diff) < max(deadband * equity, min_order):
                    continue
                if side == "SELL" and diff < 0:
                    sell_usd = cur if targets.get(c, 0.0) <= 0 else -diff
                    fill = p * (1 - slippage)
                    q = min(qty.get(c, 0.0), sell_usd / p)
                    proceeds = q * fill
                    cash += proceeds * (1 - fee)
                    fees_paid += proceeds * fee
                    qty[c] = qty.get(c, 0.0) - q
                    turnover += proceeds
                    trades += 1
                    if qty[c] * p < 1:
                        qty.pop(c, None)
                elif side == "BUY" and diff > 0:
                    buy_usd = min(diff, cash / (1 + fee))
                    if buy_usd < min_order:
                        continue
                    fill = p * (1 + slippage)
                    qty[c] = qty.get(c, 0.0) + buy_usd / fill
                    cash -= buy_usd * (1 + fee)
                    fees_paid += buy_usd * fee
                    turnover += buy_usd
                    trades += 1
        equity_curve.append((t, cash + sum(q * px[c] for c, q in qty.items())))

    eq = pd.Series(dict(equity_curve)).sort_index()
    stats = summary(eq)
    days = max(stats["days"], 1)
    stats.update(trades_per_day=trades / days, fees_pct=fees_paid / rcfg.initial_equity,
                 daily_turnover=turnover / rcfg.initial_equity / days)
    return eq, stats


def buy_and_hold(closes: pd.DataFrame, coin: str, start: str, end: str) -> dict:
    s = closes[coin].loc[start:end].dropna()
    return summary(s / s.iloc[0] * 100_000)


def window_study(eq: pd.Series, days: int = 14, step_days: int = 7) -> pd.DataFrame:
    rows = []
    t = eq.index[0]
    while t + pd.Timedelta(days=days) <= eq.index[-1]:
        seg = eq.loc[t: t + pd.Timedelta(days=days)]
        rows.append({"start": t.date(), **summary(seg)})
        t += pd.Timedelta(days=step_days)
    return pd.DataFrame(rows)


def fmt(stats: dict) -> str:
    keys = ["total_return", "max_drawdown", "sharpe", "sortino", "calmar", "composite",
            "positive_days", "trades_per_day", "fees_pct", "daily_turnover"]
    return "  ".join(f"{k}={stats[k]:.3f}" for k in keys if k in stats)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2025-06-01")
    ap.add_argument("--end", default="2026-10-10")
    ap.add_argument("--fee", type=float, default=0.001)
    ap.add_argument("--windows", action="store_true", help="14-day rolling window study")
    args = ap.parse_args()
    closes, vols = load_data(StrategyConfig().whitelist)
    eq, stats = run(args.start, args.end, fee=args.fee, closes=closes, vols=vols)
    print("STRATEGY  ", fmt(stats))
    print("BTC B&H   ", fmt(buy_and_hold(closes, "BTC", args.start, args.end)))
    out = ROOT / "data" / "backtest_equity.csv"
    eq.to_csv(out)
    if args.windows:
        w = window_study(eq)
        print(f"\n14-day windows (n={len(w)}): median return {w.total_return.median():.3%}, "
              f"P(return>0) {(w.total_return > 0).mean():.0%}, median MDD {w.max_drawdown.median():.2%}, "
              f"worst MDD {w.max_drawdown.max():.2%}, median composite {w.composite.median():.2f}")


if __name__ == "__main__":
    main()
