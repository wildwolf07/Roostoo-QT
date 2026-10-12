# Decision log

Every material change to the live bot, why we made it, and the evidence behind it. Times are UTC.
The live bot only ever runs committed code, deployed with `deploy/deploy.sh`, so each decision maps
to a commit. Ideas we tested and rejected are at the end, with their numbers.

## Timeline

| # | Date | Decision | Commit |
|---|---|---|---|
| 1 | Oct 9 | v0 → v1: drop the fast trend + regime gate; trade 7–14 day momentum, 3 daily tranches | `d54caaa` |
| 2 | Oct 9 | Go live with v1 on the competition account | `393fc0d` |
| 3 | Oct 10 | v1 → v2: equal-weight ensemble of 4 sleeves | `8c96068` |
| 4 | Oct 10 | Risk overlay recalibrated: CPPI floor and 24h loss limit removed | `80a8062` |
| 5 | Oct 10 | Universe 15 → 25 coins; PEPE and SHIB excluded | `640a349` |
| 6 | Oct 10 | Per-coin trailing stops disabled | `0412056` |
| 7 | Oct 10 | Drawdown brake → catastrophe-only (6–12%) | `39a452d` |
| 8 | Oct 10 | Operational hardening: data fallbacks, stale-order cancel, bounded retries | `8b55426`, `b1673d0` |
| 9 | Oct 10 | Contingency sleeve mix made a config switch (default unchanged) | `203166a` |
| 10 | Oct 10 | Leaderboard check: no change | — |
| 11 | Oct 10 | Endgame lock-in: exposure scales down as the contest gain is banked | `5d8d2a7` |
| 12 | Oct 11 | Lock-in floor 0.15×; daily safety net 20:00 → 12:00 UTC | `1df8a40` |
| 13 | Oct 11 | Lock-in: 0.10× from +0.25% banked, no re-risking while positive | `226934d` |
| 14 | Oct 11 | Audit fixes: $50 trade threshold for a small book, cached market data | `9087f5b` |
| 15 | Oct 11 | Lock-in floor 0.075×; competitor model calibrated with public data | `c9731da` |
| 16 | Oct 11 | Contest window corrected to 12:00–12:00 UTC; safety net at 10:00 UTC | `ffdd15d` |

## Details

### 1. v0 → v1: slow momentum (Oct 9)
- v0 (fast hourly trend plus a BTC regime gate) lost money in 69 two-week backtests, with fees about
  equal to the losses.
- A rank-IC diagnosis showed 1–24h returns **mean-revert** (t ≈ −14), while 7–14 day relative
  strength persists.
- v1: a 50/50 blend of long-only trend and market-neutral cross-sectional momentum, rebalanced daily in
  3 tranches.

### 2. Go live (Oct 9)
- Verified with a full cycle on the Roostoo test account first. That test found and fixed a
  short-collateral double count in the equity calculation.

### 3. v2: four-sleeve ensemble (Oct 10)
- A 3.8-year, 31-coin study, in-sample vs out-of-sample. The ensemble had the best Sharpe (0.73 at the
  time, 15-coin universe), the lowest drawdown, and was positive in every year.
- Sleeves: momentum L/S (beta-neutral), momentum long-only, filtered momentum L/S (no lottery longs,
  only calm shorts), low-risk long-only.
- Live code reproduces the research weights exactly (parity difference 8e-17).

### 4. Risk overlay recalibrated (Oct 10)
- Replaying the live overlay on every 14-day window showed the tight overlay (CPPI floor, 24h limit,
  tight brake) *reduced* the out-of-sample median composite from +2.67 to −0.78, because it sold dips
  and missed rebounds.

### 5. Universe 15 → 25 coins (Oct 10)
- Breadth study: Sharpe 0.89 → 1.27; every year above 1.0; flat across 3–5 coins per side
  (Grinold's fundamental law).
- PEPE and SHIB excluded for 18–25 bp spreads on Roostoo.

### 6. Per-coin stops disabled (Oct 10)
- Every stop setting (3–8%, 6–15%, 10–25%) lowered Sharpe in both periods (1.27 → 0.75 for 6–15%) and
  did not reduce max drawdown.
- The ensemble lost only 2.3% in the 2025-10-10 crash, against a 20.6% market fall.

### 7. Catastrophe-only drawdown brake (Oct 10)
- At the live configuration, a 2.5–7% brake cut the median 14-day composite in both periods (in-sample
  2.32 → 1.40, out-of-sample 5.00 → 4.21).
- A 6–12% brake matches "no overlay" on the median and still trims the worst case.

### 8. Operational hardening (Oct 10)
- From a code review of live failure modes: Binance fallback hosts, cancel stale orders on restart,
  and retry a failed daily rebalance up to 5 times. Unit-tested.

### 9. Contingency switch (Oct 10)
- A pre-validated alternative sleeve mix (long momentum + low-risk at a higher volatility target),
  available as a config value in case the top-20 return cutoff turned out high. Never used.

### 10. Leaderboard check (Oct 10)
- Live leaderboard: #8 of 190 overall, #3 in India at +1.0%.
- `scripts/leaderboard_decision.py`: more risk only lowers the probability of staying above the
  top-20 cutoff when already ahead. No change.

### 11. Endgame lock-in (Oct 10)
- The finalists' portfolio score is a set of **ratios over a fixed window** (Sortino, Sharpe, Calmar).
  Ratios are scale-free only while nothing is banked. Once a gain is banked, extra risk grows the
  denominators faster than the numerators.
- `research/endgame.py`: 5,350 historical 7.3-day stretches with fees, four readings of the
  unpublished formula. With +1% banked, cutting exposure raised the median composite from 10.6 to
  30.0 and scored higher at every quantile (stochastic dominance). P(final return < 0) fell from 22%
  to 8%. Median return fell from +1.20% to +1.15%.
- First rule: exposure from 1× to 0.25× as the banked return goes 0 → +1%. The deadband scales with
  exposure.

### 12. Lock-in floor 0.15×; safety net 12:00 UTC (Oct 11)
- Real India leaderboard: the 20th team was at −5.2%, so the top-20 return cut was not binding.
- On that field, P(top 5 by composite): 62% at 1×, 90% at a 0.25× floor, 93–94% at a 0.15× floor.
- If trading days are counted in HKT, our live days were exactly 8, so a 20:00 UTC safety-net trade
  could land on the next HKT day. Moved to 12:00 UTC.

### 13. No re-risking while positive (Oct 11)
- After an overnight dip (+1.1% → +0.65%), the first rule would have raised exposure to 0.45× to win
  return back. With the return cut far below zero, that only adds loss risk.
- From the real state: P(loss) 13% → 1%, P(top 5 by composite) 79% → 94%. New rule: 1× → 0.10× as
  the banked return goes 0 → +0.25%.

### 14. Audit fixes (Oct 11)
- A dry run of the order planner on 365 days at 0.10× gave about 3 orders a day, with fewer than 3
  on 38% of days. That is thin for the "enough trades each day" rule. Below 0.5× the bot now trades
  every update of $50 or more: about 13 orders a day, never fewer than 3, for about $1.40 a day in fees.
- If every Binance host failed for a day, the bot would have skipped trading. It now trades on the
  last good bars.
- Closed form (docs/ENDGAME.md): k\*_Sharpe ≈ 0.05, k\*_Sortino ≈ 0.003. Simulation: P(top 5) is flat
  at about 87% for 0–0.10×.

### 15. Floor 0.075×; competitor model calibrated (Oct 11)
- Competitors' portfolios and order histories are public in the Roostoo app. Rebuilding the leading
  team's equity curve from its orders and Binance prices (it matches the app to 0.07%) gave a 0.57%
  drawdown on a 30% long-only book. Any team below water has a drawdown at least equal to its loss.
- With these profiles: P(top 5) 85.8% at 0.10× vs 86.1% at 0.075×; P(#1) 20.2% → 23.2%.
- 0.075× lies between the closed-form Sharpe optima (0.05–0.08) and still gives at least 3 orders
  every day in the 365-day dry run (0.05×: fewer than 3 on 3% of days).

### 16. Contest window and safety-net hour (Oct 11)
- The hackathon page gives the window as Oct 4 17:30 – Oct 18 17:30 India time, which is
  12:00–12:00 UTC. The bot was set to stop at Oct 17 23:59 UTC, 12 hours early, and would have skipped
  the Oct 18 00:01 UTC rebalance.
- A 12:00 UTC safety net sits exactly on a 12:00 UTC day boundary. 10:00 UTC is inside the same day
  under every convention (UTC, HKT, IST, contest days).
- The endgame study re-run on the corrected window: P(top 5) 88.9% at 0.075×, against 48.6% at 1×.

## Ideas tested and rejected

| Idea | Why it looked promising | Why we rejected it |
|---|---|---|
| Fast hourly trend + BTC regime gate (v0) | Classic trend-following | Lost money; fees equal to the losses; the regime gate had no predictive value |
| Short sleeve in a risk-off regime | Profit in downtrends | Made every v0 variant worse |
| Low-risk long/short (short volatile / lottery coins) | Strong negative IC (t ≈ −6) | Sharpe −1.1: rare pumps in the shorted coins dominate. **IC ≠ P&L** with fat tails |
| BTC → altcoin catch-up, 8h | IC t-stat 13–16 | Turnover 1.4× a day, so fees win (Sharpe −3.2) |
| Short-term reversal | Most pairs reverse | Edge of 1–2 bp, below fees |
| Execution timing via reversal / catch-up | No extra turnover | Saves only 1–2 bp per trade |
| Funding-rate crowding | Practitioner evidence | Significant in-sample, about zero out-of-sample |
| Market timing (breadth, funding, premium, order flow, vol ratio) | Would capture market direction | Nothing significant in both periods |
| Tight risk overlay (CPPI 96%, 1.5–4.5% brake, 24h limit) | Lower drawdown | Whipsaw: out-of-sample composite −0.78 vs +2.70 |
| Per-coin trailing stops | Cut losers early | Sell on noise and miss recoveries; every setting lowered Sharpe in both periods |
| Bear filter: long-only sleeves off when BTC is below its 50-day average | Avoid prolonged bears (2022) | Full-period Sharpe 1.08 → 1.55, but the median 14-day composite *falls* 3.27 → 1.95 (it lags rebounds). Kept as a contingency |
| Residual (idiosyncratic) momentum | Better on 2023–26 (Sharpe 1.27 → 1.53) | Worse on the unseen 2021–22 data (median 14-day composite 2.73 → 1.59) |
| Volatility-managed scaling (Moreira–Muir) | Classic Sharpe booster for momentum | Full Sharpe 1.08 → 0.73–1.00, worse 2022, higher max drawdown |
| Removing the end-of-contest taper; other deadbands | Small score gains | Mixed across periods, so unchanged |
| 14 more Roostoo coins (ONDO, PENGU, SEI, …) | Breadth helped in the survivorship test | Better recent results, but worse 2021–22 and full Sharpe (0.92–1.00 vs 1.08) |
| A higher volatility target (1.6–2.0%) | Larger returns | Composite unchanged, fatter loss tail |
| An all-in bet to chase the overall #1 return | The only way to reach +37% in 7 days | `research/moonshot.py`: reaches it in 5.7% of stretches but loses money 52% of the time; halves P(finalist) |

## Process safeguards
- In-sample (2023-01 → 2025-05) vs out-of-sample (2025-06 → 2026-10) for every signal and portfolio,
  plus the unseen 2021–22 period.
- Fees always charged at the taker rate (0.1%), which is conservative versus our maker-first execution.
- Few variants per study and plateau checks, to limit backtest overfitting (Bailey & López de Prado).
- Parity test: the live strategy code equals the research code.
- Test-account dry runs before live deploys. The competition key is never used outside the bot.
