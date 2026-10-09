# Decision Log

Every material change to the live bot, why we made it, and the evidence behind it. All times
are UTC. Each entry maps to a commit in this repository; the live bot only ever runs
committed code, deployed with `deploy/deploy.sh`.

| # | Date | Decision | Evidence | Commit |
|---|---|---|---|---|
| 1 | Oct 9 | **v0 → v1.** Dropped the fast hourly trend strategy with a BTC regime gate. Moved to slow (7–14 day) momentum: a 50/50 blend of long-only trend and market-neutral cross-sectional momentum, rebalanced daily in 3 tranches | v0 lost money in 69 two-week backtests, with fees about equal to the losses. A rank-IC diagnosis showed short lookbacks *mean-revert* while 7–14 day relative strength persists | `d54caaa` |
| 2 | Oct 9 | **Go live with v1** on the competition account (initial equity $100,000) | Verified with a real cycle on the test account. Fixed a short-collateral double count found in that test | `393fc0d` |
| 3 | Oct 10 | **v1 → v2 ensemble** of 4 sleeves: momentum L/S (beta-neutral), momentum long-only, filtered momentum L/S (no lottery longs, only calm shorts), low-risk long-only | 3.8-year, 31-coin study, in-sample vs out-of-sample. The ensemble had the best Sharpe (0.73) and lowest drawdown, and was positive in every year. Live code reproduces research weights exactly (parity 8e-17) | `8c96068` |
| 4 | Oct 10 | **Risk overlay recalibrated.** Removed the CPPI floor and the 24h loss limit. Drawdown brake loosened to 2.5–7%. Stops widened to disaster-only (6–15%) | Replaying the live overlay on every 14-day window showed the tight overlay *reduced* the OOS median composite from +2.67 to −0.78 (whipsaw) | `80a8062` |
| 5 | Oct 10 | **Universe 15 → 25 of 29 coins**; PEPE and SHIB removed | Breadth study: Sharpe 0.89 → 1.27, every year above 1.0, flat across 3–5 coins per side. PEPE/SHIB have 18–25 bp spreads on Roostoo | `640a349` |
| 6 | Oct 10 | **Per-coin trailing stops disabled** (the portfolio drawdown brake stays) | Stops cut Sharpe from 1.27 to 0.75 and lowered the in-sample *and* out-of-sample results without reducing max drawdown. The ensemble lost only −2.3% in the 2025-10-10 crash (market −20.6%) | `0412056` |

## Ideas tested and rejected (with numbers)

| Idea | Why it looked promising | Why we rejected it |
|---|---|---|
| Fast hourly trend + BTC regime gate (v0) | Classic trend-following | Lost money; fees equal to the losses; the regime gate had no predictive value (forward basket return was negative in every regime) |
| Short sleeve in RISK_OFF | Profit in downtrends | Made every v0 variant worse |
| Low-risk long/short (short high-vol / lottery coins) | Strong negative IC (t ≈ −6) | Sharpe −1.1: rare pumps in shorted coins dominate. **IC ≠ P&L** with fat tails |
| BTC → altcoin catch-up, 8h | IC t-stat 13–16 | Turnover 1.4×/day, so fees win (Sharpe −3.2) |
| Short-term reversal | 90% of pairs reverse (literature) | Edge 1–2 bp, below fees |
| Execution timing via reversal / catch-up | Zero-turnover idea | Saves only 1–2 bp per trade |
| Funding-rate crowding | Practitioner evidence | Significant in-sample, ~0 out-of-sample |
| Market timing (breadth, funding, premium, order flow, vol ratio) | Would capture market direction | Nothing significant in both periods |
| Tight risk overlay (CPPI 96%, 1.5–4.5% brake, 24h limit) | Lower drawdown | Whipsaw: OOS composite −0.78 vs +2.70 |
| Per-coin trailing stops (3–8%, 6–15%, 10–25%) | Cut losers early | Sell on noise and miss recoveries; every setting lowered Sharpe in both periods |
| Higher vol target (1.6–2.0%) | Larger returns | Composite unchanged, fatter loss tail. Kept at 1.2% unless the leaderboard demands more |

## Process safeguards
- In-sample (2023-01 → 2025-05) vs out-of-sample (2025-06 → 2026-10) for every signal and portfolio.
- Fees always charged at the taker rate (0.1%), which is conservative versus our maker-first execution.
- Few variants per study and plateau checks, to limit backtest overfitting (Bailey & López de Prado).
- Parity test: live strategy code equals research code.
- Test-account dry runs before every live deploy. The competition key is never used outside the bot.
