"""Read-only performance report from the bot's own SQLite log (no API calls).

Usage: python -m scripts.daily_report [--mode live]
"""
from __future__ import annotations

import argparse
import sqlite3

import pandas as pd

from bot.config import RuntimeConfig
from bot.metrics import summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="live")
    args = ap.parse_args()
    db = RuntimeConfig().db_path.with_name(f"bot_{args.mode}.db")
    con = sqlite3.connect(db)
    eq = pd.read_sql("SELECT ts, equity, gross_exposure, drawdown FROM equity", con, parse_dates=["ts"])
    if eq.empty:
        print("no equity data yet")
        return
    eq = eq.set_index("ts")
    print(f"equity {eq.equity.iloc[-1]:,.2f}  gross {eq.gross_exposure.iloc[-1]:.2%}  dd {eq.drawdown.iloc[-1]:.2%}")
    if len(eq) > 60:
        stats = summary(eq.equity)
        print("  ".join(f"{k}={v:.3f}" for k, v in stats.items()))
    orders = pd.read_sql("SELECT ts, pair, side, type, quantity, status, avg_price, reason FROM orders "
                         "ORDER BY ts DESC LIMIT 15", con)
    print("\nrecent orders:\n", orders.to_string(index=False))
    calls = pd.read_sql("SELECT success, COUNT(*) n FROM api_calls GROUP BY success", con)
    print("\napi calls by success:\n", calls.to_string(index=False))


if __name__ == "__main__":
    main()
