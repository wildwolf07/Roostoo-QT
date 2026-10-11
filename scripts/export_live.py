"""Forward-test (live) results as a Markdown block, read-only from the bot's own SQLite log.

Prints the contest-window summary, one row per contest day (days run 12:00 to 12:00 UTC, as the
organisers' window does), and execution statistics. Copy the output into
results/forward_test/LIVE_RESULTS.md. No API calls; safe to run while the bot is trading.

Usage (EC2): cd /opt/roostoo-bot && sudo -u ec2-user .venv/bin/python -m scripts.export_live
"""
from __future__ import annotations

import argparse
import sqlite3

import pandas as pd

from bot.config import RuntimeConfig
from bot.metrics import summary

CONTEST_START = pd.Timestamp("2026-10-04 12:00", tz="UTC")
DAY_SHIFT = pd.Timedelta(hours=12)          # contest days start at 12:00 UTC (17:30 IST)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="live")
    args = ap.parse_args()
    con = sqlite3.connect(RuntimeConfig().db_path.with_name(f"bot_{args.mode}.db"))
    eq = pd.read_sql("SELECT ts, equity, gross_exposure FROM equity", con)
    eq["ts"] = pd.to_datetime(eq["ts"], utc=True, format="ISO8601")
    eq = eq.set_index("ts").sort_index()
    init = pd.read_sql("SELECT value FROM kv WHERE key='initial_equity'", con)
    initial = float(init.value.iloc[0]) if not init.empty else float(eq.equity.iloc[0])
    orders = pd.read_sql("SELECT ts, pair, side, type, status, filled_qty, avg_price, commission FROM orders", con)
    orders["ts"] = pd.to_datetime(orders["ts"], utc=True, format="ISO8601")
    calls = pd.read_sql("SELECT success, COUNT(*) AS n FROM api_calls GROUP BY success", con)

    hourly = eq.equity.resample("1h").last().dropna()
    first_live = hourly.index[0]
    window = pd.concat([pd.Series([initial], index=[CONTEST_START]), hourly]).resample("1h").last().ffill()
    shifted = window.copy()
    shifted.index = shifted.index - DAY_SHIFT                 # daily returns on contest-day boundaries
    st = summary(shifted)
    now = hourly.index[-1]
    account = "competition account" if args.mode == "live" else f"{args.mode} account"
    print(f"## Live forward test: Roostoo {account} (exported {now:%Y-%m-%d %H:%M} UTC)\n")
    print(f"- Bot live since **{first_live:%Y-%m-%d %H:%M} UTC**; contest window starts {CONTEST_START:%Y-%m-%d %H:%M} UTC "
          f"(flat cash before we went live).")
    print(f"- Equity **{hourly.iloc[-1]:,.2f}** from {initial:,.2f}: return **{hourly.iloc[-1] / initial - 1:+.2%}**, "
          f"max drawdown **{st['max_drawdown']:.2%}**.")
    no_loss = st["sortino"] == 0 and st["total_return"] > 0          # no losing day: downside deviation is 0
    sortino = "unbounded (no losing day yet)" if no_loss else f"{st['sortino']:.2f}"
    composite = "n/a while Sortino is unbounded" if no_loss else f"{st['composite']:.2f}"
    print(f"- Contest-window ratios (daily returns, 365-day annualisation, our reconstruction of the formula): "
          f"Sortino {sortino}, Sharpe {st['sharpe']:.2f}, Calmar {st['calmar']:.2f}, composite {composite}.\n")

    print("| Contest day (from 12:00 UTC) | End equity | Day return | Max gross exposure | Orders sent | Filled | Fees |")
    print("|---|---|---|---|---|---|---|")
    day_eq = shifted.resample("1D").last()
    day_ret = day_eq.pct_change()
    gross = eq.gross_exposure.copy()
    gross.index = gross.index - DAY_SHIFT
    od = orders.copy()
    od["day"] = (od.ts - DAY_SHIFT).dt.floor("1D")
    filled_mask = od.status.isin(["FILLED", "OPEN", "CLOSED"])
    for d, v in day_eq.items():
        if d < (first_live - DAY_SHIFT).floor("1D"):
            continue
        g = gross.loc[d: d + pd.Timedelta(hours=23, minutes=59)]
        o = od[od.day == d]
        print(f"| {d:%Y-%m-%d} | {v:,.2f} | {day_ret.get(d, float('nan')):+.2%} | "
              f"{(g.max() if len(g) else float('nan')):.1%} | {len(o)} | {int(filled_mask[o.index].sum())} | "
              f"${o.commission.fillna(0).sum():,.2f} |")

    f = orders[filled_mask]
    spot = f[f.side.isin(["BUY", "SELL"])].copy()
    notional = (spot.filled_qty * spot.avg_price).where(lambda x: x > 0)
    rate = spot.commission / notional
    maker = int((rate < 0.00075).sum())
    print(f"\n- Orders: {len(orders)} sent, {len(f)} filled or open, "
          f"{int((orders.status == 'CANCELED').sum())} limit orders cancelled then re-planned. Spot fills paying the maker fee: "
          f"{maker} of {int(rate.notna().sum())}.")
    print(f"- Fees paid: ${orders.commission.fillna(0).sum():,.2f} ({orders.commission.fillna(0).sum() / initial:.3%} of initial equity).")
    ok_n = int(calls.loc[calls.success == 1, "n"].sum())
    print(f"- API calls: {int(calls.n.sum())}, {ok_n / max(int(calls.n.sum()), 1):.2%} successful.")


if __name__ == "__main__":
    main()
