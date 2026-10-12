## Live forward test: Roostoo competition account (exported 2026-10-12 06:00 UTC)

Exported with `python -m scripts.export_live --curve` (a read-only query of the bot's SQLite audit log).
Hourly equity: [`live_equity.csv`](live_equity.csv). Chart: [`../../docs/img/live.svg`](../../docs/img/live.svg).

- Bot live since **2026-10-09 21:51 UTC**; the contest window starts 2026-10-04 12:00 UTC (flat cash before we went live).
- Equity **101,038.96** from 100,000.00: return **+1.04%**, max drawdown **0.44%** (hourly marks).
- Contest-window ratios by our reconstruction of the formula (daily returns on 12:00 UTC day boundaries, 365-day
  annualisation, flat days included): Sortino 26.88, Sharpe 6.72, Calmar 143.96, composite 55.95. These are
  annualised from three live days, so they compare teams under the contest's formula but say little about the
  long-run edge (section 4 of the README).

| Contest day (from 12:00 UTC) | End equity | Day return | Max gross exposure | Orders sent | Filled | Fees |
|---|---|---|---|---|---|---|
| 2026-10-09 | 100,947.08 | +0.95% | 64.4% | 30 | 24 | $97.52 |
| 2026-10-10 | 100,683.48 | −0.26% | 64.8% | 24 | 19 | $42.61 |
| 2026-10-11 | 101,038.96 | +0.35% | 23.4% | 23 | 20 | $16.01 |

- Orders: 77 sent, 63 filled or open; 14 limit orders cancelled after 3 minutes and re-planned at market.
  **21 of 40 spot fills paid the 0.05% maker fee.**
- Fees paid: $156.14 (0.156% of initial equity).
- API calls: 10,428, **99.93% successful**.
- Endgame lock-in (docs/ENDGAME.md): at the 2026-10-12 00:01 UTC rebalance the risk multiplier went to ×0.075
  (`risk_mult=0.07` in the log): 23 orders, gross exposure 5.0%, tracking error 0.01%. Since then equity moves by
  a few dollars an hour.
