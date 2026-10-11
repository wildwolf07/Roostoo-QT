# Results

| Folder | Contents | How it is produced |
|---|---|---|
| [`backtest/`](backtest/) | `SUMMARY.md` (one page), `daily_equity.csv` (strategy vs BTC vs equal-weight market, 2021–2026), `yearly.csv`, `windows_14d.csv` (every 14-day window with Sortino, Sharpe, Calmar and composite), `crash_events.csv` | `python -m research.make_results` (after `research.download_pre` and `research.download_full`) |
| [`forward_test/`](forward_test/) | Live results on the Roostoo competition account: daily equity, exposure, orders, fills, fees, API health | `python -m scripts.export_live` on the server, a read-only query of the bot's SQLite audit log |

All backtests use the live configuration and charge the 0.1% taker fee on every fill.
