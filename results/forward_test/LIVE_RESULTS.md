## Live forward test: Roostoo competition account (exported 2026-10-14 14:00 UTC)

Exported with `python -m scripts.export_live --curve` (a read-only query of the bot's SQLite audit log).
Hourly equity: [`live_equity.csv`](live_equity.csv). Chart: [`../../docs/img/live.svg`](../../docs/img/live.svg).
The bot keeps trading until the contest ends (Oct 18 12:00 UTC).

- Bot live since **2026-10-09 21:51 UTC**; the contest window starts 2026-10-04 12:00 UTC (flat cash before we went live).
- Equity **100,939.04** from 100,000.00: return **+0.94%**, max drawdown **0.44%** (hourly marks).
- Contest-window ratios by our reconstruction of the formula (daily returns on 12:00 UTC day boundaries, 365-day
  annualisation, flat days included): Sortino 20.20, Sharpe 5.15, Calmar 92.43, composite 37.35. These are
  annualised from a few live days, so they compare teams under the contest's formula but say little about the
  long-run edge (section 4 of the README).

| Contest day (from 12:00 UTC) | End equity | Day return | Max gross exposure | Orders sent | Filled | Fees |
|---|---|---|---|---|---|---|
| 2026-10-09 | 100,947.08 | +0.95% | 64.4% | 30 | 24 | $97.52 |
| 2026-10-10 | 100,683.48 | −0.26% | 64.8% | 24 | 19 | $42.61 |
| 2026-10-11 | 101,027.73 | +0.34% | 23.4% | 23 | 20 | $16.01 |
| 2026-10-12 | 100,972.66 | −0.05% | 5.2% | 14 | 14 | $1.35 |
| 2026-10-13 | 100,963.95 | −0.01% | 5.2% | 14 | 12 | $1.47 |
| 2026-10-14 (in progress) | 100,939.04 | −0.02% | 4.2% | 0 | 0 | $0.00 |

The 2026-10-14 contest day had run for 2 hours at export time; its rebalance falls at 00:01 UTC on Oct 15.

- Orders: 105 sent, 89 filled or open; 16 limit orders cancelled after 3 minutes and re-planned at market.
  **30 of 55 spot fills paid the 0.05% maker fee.**
- Fees paid: $158.97 (0.159% of initial equity).
- API calls: 20,553, **99.95% successful**.
- Endgame lock-in (docs/ENDGAME.md): ×0.34 at the 2026-10-11 rebalance, ×0.075 from 2026-10-12. Gross exposure
  fell from 64% to about 5%, and daily moves since then are a few hundredths of a percent.
