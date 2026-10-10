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
| 7 | Oct 10 | **Drawdown brake 2.5–7% → catastrophe-only 6–12%** | At the live 25-coin config the 2.5–7% brake cut the median 14-day composite in both periods (IS 2.32 → 1.40, OOS 5.00 → 4.21). The 6–12% brake equals 'no overlay' on the median and still trims the worst-case drawdown | `39a452d` |
| 8 | Oct 10 | **Operational hardening**: Binance data fallback hosts, cancel stale orders on restart, a failed daily rebalance retried up to 5× | Found in a code review of live failure modes; unit-tested | `8b55426`, `b1673d0` |
| 9 | Oct 10 | **Plan B made a config switch** (sleeve weights), default unchanged | Pre-validated so a high top-20 cutoff can be answered without new code mid-contest | `203166a` |
| 10 | Oct 10 | **Leaderboard check → stay on Plan A (no change)** | Live leaderboard (Oct 10, 08:32 UTC): we are #8 of 190 overall and #3 in India at +1.0% (India #1 +1.6%, #2 +1.3%). `scripts/leaderboard_decision.py`: P(finishing above India #20) is 77.5% on Plan A vs 73.4% on A+ and 66.4% on B (if #20 ends at 0%). Extra risk only lowers our odds when ahead | — |
| 11 | Oct 10 | **Endgame lock-in.** From Oct 10 12:00 UTC, exposure falls linearly from 1× (nothing banked) to 0.25× once the contest return reaches +1%, and rises again if the gain shrinks. The deadband scales with exposure so the smaller book still tracks its targets | Finalists are ranked by Sortino/Sharpe/Calmar *after* the top-20 return cut, and those ratios are scale-free only while nothing is banked. `research/endgame.py` (2,675–5,350 historical 7.3-day stretches, fees included) with +1% banked: median composite 10.6 → 30.0 and 25th percentile 0.8 → 14.0. It scores higher at every quantile from 5% to 95% (stochastic dominance), under all four readings of the unpublished formula. P(final return < 0) 22% → 8%, P(< +0.5%) 33% → 14%. Median return +1.20% → +1.15%. With a modelled India field, P(top 20 by return) is about unchanged (79–89% → 83–87%) and P(top 20 and top 5 by composite) rises from 33–41% to 62–67% | see git log |

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
| Bear filter: long-only sleeves off when BTC < 50-day average | Avoid prolonged bears (2022) | Full-period Sharpe 1.08 → 1.55, but the median 14-day composite *falls* 3.27 → 1.95 (it lags and misses rebounds). Kept as a contingency |
| Residual (idiosyncratic) momentum | Better on 2023–26 (Sharpe 1.27 → 1.53) | Worse on unseen 2021–22 (median 14d composite 2.73 → 1.59) |
| Volatility-managed scaling (Moreira–Muir) | Classic Sharpe booster for momentum | Full Sharpe 1.08 → 0.73–1.00, worse 2022, higher max DD |
| End-of-contest taper removal / 2% deadband changes | Small score gains | Mixed across periods, so unchanged |
| Add 14 more Roostoo coins (ONDO, PENGU, SEI, …) | Breadth helped in the survivorship test | Better recent OOS, but worse 2021–22 and full Sharpe (0.92–1.00 vs 1.08) |
| All-in concentrated bet to chase the overall #1 return (+37%, an AU-region team) | Only way to reach +37% in 7 days | `research/moonshot.py`: 95% in the most volatile coin reaches +37% in 5.7% of historical stretches, but P(loss) 52%, P(loss > 10%) 22%. P(top 20 in region) falls 84–87% → 48–50%, P(top 5 by composite) 62–68% → 29–30%, P(#1 by composite) is no better (20–21% vs 18–25% for the lock-in). It also breaks consistency with the declared strategy |
| Higher vol target (1.6–2.0%) | Larger returns | Composite unchanged, fatter loss tail. Kept at 1.2% unless the leaderboard demands more |

## Process safeguards
- In-sample (2023-01 → 2025-05) vs out-of-sample (2025-06 → 2026-10) for every signal and portfolio.
- Fees always charged at the taker rate (0.1%), which is conservative versus our maker-first execution.
- Few variants per study and plateau checks, to limit backtest overfitting (Bailey & López de Prado).
- Parity test: live strategy code equals research code.
- Test-account dry runs before every live deploy. The competition key is never used outside the bot.
