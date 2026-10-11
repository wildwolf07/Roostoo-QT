"""Read-only performance report from the bot's own SQLite log (no API calls).

Shows equity, exposure, our estimate of the competition composite score (the judges'
window starts Oct 4 12:00 UTC; days before the bot went live count as flat), recent orders with
their final fill status, fee totals and API health.

Usage: python -m scripts.daily_report [--mode live]
"""
from __future__ import annotations

import argparse
import sqlite3

import pandas as pd

from bot.config import RuntimeConfig
from bot.metrics import summary

CONTEST_START = pd.Timestamp("2026-10-04 12:00", tz="UTC")   # Oct 4 17:30 IST
# backtest reference (RESEARCH.md v2, 14-day windows, out-of-sample): median / 95th pct
BACKTEST_REF = {"median 14d return": "+0.3% to +0.6%", "median 14d max DD": "2.5-2.8%", "p95 14d max DD": "~5%"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="live")
    args = ap.parse_args()
    db = RuntimeConfig().db_path.with_name(f"bot_{args.mode}.db")
    con = sqlite3.connect(db)
    eq = pd.read_sql("SELECT ts, equity, gross_exposure, drawdown FROM equity", con)
    if eq.empty:
        print("no equity data yet")
        return
    eq["ts"] = pd.to_datetime(eq["ts"], utc=True, format="ISO8601")
    eq = eq.set_index("ts").sort_index()
    init = pd.read_sql("SELECT value FROM kv WHERE key='initial_equity'", con)
    initial = float(init.value.iloc[0]) if not init.empty else float(eq.equity.iloc[0])
    last = eq.iloc[-1]
    print(f"equity {last.equity:,.2f}  return {last.equity / initial - 1:+.3%}  gross {last.gross_exposure:.1%}  "
          f"drawdown {last.drawdown:.2%}")

    # contest-window series: flat at the initial equity from Oct 4 until the bot's first record
    hourly = eq.equity.resample("1h").last().dropna()
    if hourly.index[0] > CONTEST_START:
        hourly = pd.concat([pd.Series([initial], index=[CONTEST_START]), hourly])
    hourly = hourly.resample("1h").last().ffill()   # flat (cash) hours before the bot started
    if len(hourly) > 48:
        st = summary(hourly)
        print("contest-window estimate: " + "  ".join(
            f"{k}={st[k]:.3f}" for k in ("total_return", "max_drawdown", "sortino", "sharpe", "calmar", "composite")))
    print("backtest reference:", "; ".join(f"{k} {v}" for k, v in BACKTEST_REF.items()))

    daily = hourly.resample("1D").last().pct_change(fill_method=None).dropna()
    if len(daily):
        print("\ndaily returns:", "  ".join(f"{d.date()}: {r:+.2%}" for d, r in daily.tail(10).items()))

    orders = pd.read_sql("SELECT ts, pair, side, type, round(quantity, 6) AS qty, status, avg_price, commission, "
                         "reason FROM orders ORDER BY ts DESC LIMIT 15", con)
    print("\nrecent orders:\n", orders.to_string(index=False))
    fees = pd.read_sql("SELECT COALESCE(SUM(commission), 0) AS fees, COUNT(*) AS n FROM orders "
                       "WHERE status IN ('FILLED', 'OPEN', 'CLOSED')", con)
    print(f"\nfilled orders: {int(fees.n.iloc[0])}, total commission ${fees.fees.iloc[0]:,.2f} "
          f"({fees.fees.iloc[0] / initial:.3%} of initial equity)")
    calls = pd.read_sql("SELECT success, COUNT(*) n FROM api_calls GROUP BY success", con)
    print("api calls by success:", dict(zip(calls.success, calls.n)))
    errs = pd.read_sql("SELECT ts, payload FROM decisions WHERE kind='error' ORDER BY ts DESC LIMIT 3", con)
    if not errs.empty:
        print("recent loop errors:\n", errs.to_string(index=False))


if __name__ == "__main__":
    main()
