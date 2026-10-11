# Endgame: risk management for a ratio-scored, fixed-window contest

This document explains why the bot shrinks its book once a gain is banked, derives the optimal
exposure in closed form, checks it by simulation, and lists the audit behind the live settings.
Code: `bot/risk/risk_manager.py` (`exposure_multiplier`), `bot/config.py` (`lockin_*`,
`small_book_*`). Studies: `research/endgame.py`, `research/optimal_k.py`, `research/moonshot.py`.
Decisions: DECISIONS.md #11–15.

## 1. The objective

Finalists are chosen per region. A team must pass compliance (including at least 8 active trading
days) and finish in its region's top 20 by return. The top 20 are then ranked by
**0.4 · Sortino + 0.3 · Sharpe + 0.3 · Calmar** over the contest window, and the code is reviewed.
On the India leaderboard of Oct 11, the #20 return was about −5%, and only four other teams were
clearly positive. So the return screen is not binding for us. **The composite decides.**

## 2. Why ratios change the problem

Sharpe, Sortino and Calmar are invariant to leverage only while nothing is banked. Split the window's
daily returns into the realised part (sum S, second moment Q = Σr², downside second moment
Q⁻ = Σmin(r,0)², max drawdown Mₚ) and n remaining days at exposure k on a strategy with daily mean μ,
second moment s² and downside second moment d². Then

    Sharpe(k)  ≈ (S + k·n·μ) / √(Q  + k²·n·s²)
    Sortino(k) ≈ (S + k·n·μ) / √(Q⁻ + k²·n·d²)
    Calmar(k)  ≈ g(S + k·n·μ) / max(Mₚ, k·Dₙ)      (Dₙ: future max drawdown at full size)

**Result.** Setting d/dk of (S + kA)/√(B + k²C) to zero gives AB = S·k·C, so

    k*_Sharpe  = μ·Q  / (S·s²)      k*_Sortino = μ·Q⁻ / (S·d²)      k*_Calmar ≈ Mₚ / Dₙ

Read it as the **Kelly leverage μ/s² scaled by the realised variance per unit of profit Q/S**. A gain
that was earned with little variance calls for very little further risk. With no banked gain
(S → 0), k* → ∞ and the usual scale-invariance comes back. With a loss (S < 0), more risk is the
only way to make the score positive. The same logic as tournament theory: leaders cut risk and
laggards add it.

**Our numbers (Oct 11, 06:00 UTC).** Realised S = +0.654%, Q = 5.8e-5, Q⁻ = 1.6e-6,
Mₚ = 0.46%. Strategy, last 365 days: μ = +0.030% a day, σ = 0.72% (μ/s² = 5.7), median 7-day
drawdown at full size 1.67%.

| | k* |
|---|---|
| Sharpe | 0.05 (0.08 with the 2023–26 mean) |
| Sortino | 0.003 |
| Calmar | ≈ 0.28 (an upper bound: above it, new drawdowns exceed the one already booked) |

The composite weights Sortino at 0.4, so the optimum sits at the low end, around 0.0–0.1.

## 3. Simulation check (`research/optimal_k.py`)

The bot's real path so far is reconstructed from its own log: flat until it went live, +0.03% on
Oct 9, +0.75% on Oct 10, a peak of +1.12%, then +0.65% with a 0.46% drawdown. It is followed by
every historical 7-day stretch of the live strategy (2023–26, fees included), with the bot's ×0.34
in force until the next rebalance. Composite medians are shown under the daily reading; the
hourly, active-days-only and unannualised readings rank the policies the same way. P(top 5) uses the
refreshed India field, with competitors' volatility and beta calibrated from their returns.

| Exposure from the next rebalance | Median return | P(return < 0) | Composite p10 / median | P(top 5) | P(#1) |
|---|---|---|---|---|---|
| 0 (cash) | +0.64% | 0.8% | 7.7 / 22.5 | 86.7% | 29.0% |
| 0.05× | +0.65% | 0.8% | 7.4 / 21.5 | 87.5% | 22.5% |
| 0.10× (rule of Oct 11 morning) | +0.67% | 1.0% | 6.8 / 19.3 | 86.5% | 17.5% |
| 0.25× | +0.69% | 4.6% | 2.4 / 15.4 | 80.5% | 12.1% |
| 0.5× | +0.72% | 15.7% | −1.8 / 11.3 | 66.2% | 9.8% |
| 1× | +0.76% | 29.3% | −5.0 / 7.1 | 52.4% | 8.7% |
| Previous rule (re-risks after dips) | +0.92% | 13.2% | −1.5 / 18.5 | 75.1% | 14.3% |

P(top 5) is flat at about 87% anywhere from 0 to 0.10×; the rest of the risk is other teams' scores,
which we do not control. Below 0.10× only P(#1) improves. The binding constraint there is the
"enough trades made from strategies each day" rule (section 4). The live floor is **×0.075**: it lies
between the closed-form Sharpe optima (0.05–0.08), and it keeps at least 3 orders on every day of
the 365-day dry run (11 a day median). ×0.05 drops below 3 orders on 3% of days, ×0.025 on 40%.

## 3b. Calibrating the competitors with public data

Team portfolios and order histories are public in the Roostoo app (delayed 5 minutes). We used them
for the teams ahead of us in our region:
- The leading team's 15 orders and fill prices let us rebuild its hourly equity curve from Binance
  prices. It matches the app's equity to 0.07%, and its cash to the dollar. It has a 0.57% max
  drawdown and a 30% long-only book.
- The other two hold large, active long/short or small-cap books, with drawdowns estimated at 2–3%.
- A team below water has a max drawdown at least as large as its loss, since every team started at
  its peak.

With these profiles (`--field-mdd`, `--field-beta`), the live rule gives P(top 5) ≈ 85.5% and
P(#1) ≈ 20–23%. The optimal floor is unchanged.

| Floor | Orders a day (median, p10) | Days with < 3 orders | P(top 5) | P(#1) |
|---|---|---|---|---|
| 0.10× | 13, 10 | 0% | 85.8% | 20.2% |
| **0.075× (live)** | **11, 7** | **0%** | **86.1%** | **23.2%** |
| 0.05× | 8, 4 | 3% | 86.1% | 26.9% |
| 0.025× | 3, 1 | 40% | 86.4% | 31.5% |

Going the other way does not help. An all-in bet on one coin, the only way to chase the overall
#1 return (+37%, a team in another region), loses money in about half of the stretches and halves
P(finalist) (`research/moonshot.py`).

## 4. Audit of the live settings (Oct 11)

| Check | Finding | Action |
|---|---|---|
| Simulator score vs `bot/metrics.py` | Same formula; small differences only from the day-boundary convention | none |
| Simulator start state | It assumed 1× until the next rebalance, but the bot was at ×0.34. That overstated loss risk | `--k-now`; real path from waypoints (`--path`) |
| Lock-in rule | Re-risked as the gain shrank (×0.45 after the dip). That only helps when the top-20 return cut binds, which it does not in India | ×0.10 from +0.25% banked (DECISIONS #13) |
| Daily activity at ×0.10 | Order planner dry-run on 365 days: ~3 orders a day, with fewer than 3 on 38% of days | $50 trade threshold for small books: ~13 a day, never fewer than 3, ~$1.40/day fees (DECISIONS #14) |
| 8 active days in HKT or IST | Our first trade (Oct 9 21:51 UTC) falls on Oct 10 in HKT and IST, so there is zero slack | safety net at 12:00 UTC: same calendar day in UTC, HKT and IST (DECISIONS #12) |
| Market-data outage | If every Binance host failed all day, the bot would skip the day | cache of the last good bars; trade on slightly stale bars (DECISIONS #14) |
| Restart behaviour | A deploy does not trigger a rebalance; the change applies at the next 00:01 UTC | documented in RUNBOOK |
| Exchange limits | MiniOrder $1, short collateral ≥ $1; our minimum is $50 | none |

## 5. Literature

- Brown, Harlow & Starks (1996), "Of Tournaments and Temptations", *Journal of Finance* 51(1):
  mid-year losers raise risk, winners lower it.
- Chevalier & Ellison (1997), "Risk Taking by Mutual Funds as a Response to Incentives", *Journal of
  Political Economy* 105(6).
- Basak, Pavlova & Shapiro (2007), "Optimal Asset Allocation and Risk Shifting in Money Management",
  *Review of Financial Studies* 20(5): optimal risk shifting under convex, evaluation-period incentives.
- Browne (1999), "Reaching Goals by a Deadline", *Advances in Applied Probability* 31(2): the policy
  that maximises the probability of a target by a deadline.
- Carpenter (2000), "Does Option Compensation Increase Managerial Risk Appetite?", *Journal of
  Finance* 55(5): convex payoffs make managers cut risk once in the money.
- Grossman & Zhou (1993), "Optimal Investment Strategies for Controlling Drawdowns", *Mathematical
  Finance* 3(3).
- Magdon-Ismail & Atiya (2004), "On the Maximum Drawdown of a Brownian Motion", *Journal of Applied
  Probability* 41(1); "Maximum Drawdown", *Risk* 17(10): drawdown and Calmar scaling with time.
- Lo (2002), "The Statistics of Sharpe Ratios", *Financial Analysts Journal* 58(4): estimation error
  of Sharpe ratios over short samples.
- Sortino & Price (1994), "Performance Measurement in a Downside Risk Framework", *Journal of
  Investing* 3(3); Young (1991), "Calmar Ratio: A Smoother Tool", *Futures*.
- Kelly (1956), "A New Interpretation of Information Rate", *Bell System Technical Journal* 35(4).
- Industry practice: multi-manager platforms cut a pod's capital after a drawdown of about 5% from
  peak (widely reported rule of thumb, not an official policy). It is the same principle applied
  to the downside: risk budgets follow realised P&L.
