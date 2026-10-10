# Research summary (TL;DR)

**Live configuration (v2.1):** an equal-weight ensemble of 4 sleeves (momentum long/short
beta-neutral, momentum long-only, filtered momentum long/short, low-risk long-only) on the 25
most liquid of 29 coins. 168h/336h momentum, 3 daily tranches (~3-day holding period), 1.2%
daily volatility target, catastrophe-only 6–12% drawdown brake, no per-coin stops,
maker-first execution.

| Evidence | Result |
|---|---|
| 2023-01 → 2026-10, fees included | +84%, Sharpe 1.27, max drawdown 16.9%, every calendar year positive |
| Unseen 2021–22 (LUNA, 3AC, FTX) | +19.8% while BTC fell −49.2% |
| 14-day windows, out-of-sample | median composite 4.0, 67% positive |
| Statistical confidence | PSR 99%, deflated Sharpe 64–71% |
| Live code = research code | parity difference 8e-17 |

How we got here: v0 (fast trend) failed → IC diagnosis → v1 (slow momentum) → 3.8-year
literature-driven signal study → v2 ensemble → overlay, breadth, stop, tail, stress and
statistics checks → v2.1. Rejected ideas and their numbers are in DECISIONS.md.

The sections below are the chronological lab notebook.

---

# Research Log: how the live strategy was chosen

All tests use Binance hourly data (Roostoo prices are streamed from Binance), 26 liquid
coins, **2025-06-01 → 2026-10-09**. Each test is **69 independent 14-day windows**
(stepped weekly), each starting fresh at $100k with the full risk overlay. This mirrors
the contest's format instead of rewarding one lucky long backtest. Fees are charged at the
**taker rate (0.1%) plus 2 bps slippage on every fill**, so results are conservative.

Market context: BTC −21% over the sample with a 54% peak-to-trough drawdown. This was a
hard, mostly bearish and choppy period.

## 1. First design failed: fast, regime-gated trend (v0)

Hourly decisions, lookbacks of 24/72/168h, BTC regime gate.

| Variant (best of 32-config grid) | Median 14d return | P(return > 0) | Median MDD | Fees / 14d |
|---|---|---|---|---|
| best: 4h rebalance, slow lookbacks, no core | −0.69% | 39% | 2.8% | 0.80% |
| worst: 1h rebalance, fast lookbacks | −2.3% | 19% | 3.5% | 1.8% |

What we learned:
- Slower rebalancing won in every pairing (4h > 1h). **Fees were roughly the size of the loss.**
- Slower lookbacks won in every pairing.
- Adding a RISK_OFF short sleeve made every variant worse.

## 2. Diagnosis: what actually predicts returns?

Rank information coefficient (IC) of vol-normalised past return vs. forward return,
measured across coins on non-overlapping samples (t-stat in brackets):

| Lookback \ forward | 8h | 24h | 72h |
|---|---|---|---|
| 6h | **−0.036 (−5.5)** | −0.020 (−1.8) | +0.010 |
| 24h | −0.023 (−3.6) | −0.010 | +0.008 |
| 168h | −0.003 | +0.011 | **+0.039 (+2.1)** |
| 336h | 0.000 | +0.019 (+1.7) | +0.022 |

- **Short-horizon returns mean-revert.** Our v0 signals were partly trading against
  this, which explains its losses.
- **Week-to-fortnight relative strength persists over the following days.** This is the
  edge we kept.
- The forward 24h basket return was negative in *every* BTC regime (RISK_ON −7.2 bps,
  NEUTRAL −4.7, RISK_OFF −3.7). The regime gate added no information in this sample,
  so it is off by default.

## 3. Redesign: slow momentum, two styles, then a blend

| Strategy | Median 14d | Mean 14d | P(>0) | Median MDD | Worst MDD | Trades/day |
|---|---|---|---|---|---|---|
| Cash (do nothing) | 0.00% | 0.00% | — | 0.00% | 0.00% | 0 |
| Trend, long-only, 72h rebalance | +0.12% | +0.52% | 54% | 3.17% | 5.20% | 1.7 |
| Cross-sectional L/S, 72h rebalance | +0.12% | +0.59% | 52% | 3.24% | 5.37% | 3.0 |
| Trend, tranched daily | −0.43% | +0.55% | 42% | 3.67% | 4.76% | 4.4 |
| Cross-sectional, tranched daily | −0.63% | −0.05% | 41% | 3.49% | 5.21% | 8.4 |
| **Blend 50/50, tranched daily (LIVE)** | **+0.05%** | **+0.29%** | **51%** | **2.77%** | **4.58%** | 7.9 |

### Why the blend was chosen
1. **Lowest drawdown of all candidates.** The two sleeves are only weakly correlated, and
   Calmar and Sortino (70% of the composite score) punish drawdown hardest.
2. **It trades every day by construction** (tranching), which the activity rule requires,
   without artificial trades.
3. **Part of the book is market-neutral**, so a crash hurts less than in a long-only book.
4. Few parameters, all chosen from the robust region of the grid, not the single best cell.

### Honest limitations
- The edge is small, and the confidence intervals of all redesigned variants overlap zero.
  The bot's real advantage is **controlled downside** in a market where many bots will take
  large swings.
- The sample is one (mostly bearish) regime. Results in a strong bull market would differ:
  long-only trend would likely beat the blend.
- Backtest stops are checked hourly. The live bot checks them every minute.

Reproduce: `python -m backtest.data_download --days 540 && python -m backtest.sweep`
(edit `grid()` in `backtest/sweep.py` to choose configurations).


---

# v2: large-scale signal study and the 4-sleeve ensemble (2026-10-10)

## Data
Binance hourly data **2023-01-01 → 2026-10-09** (33,070 bars per coin) for the **31 coins
that trade on Roostoo**, including taker-buy volume (order flow), perpetual funding rates and
the perpetual premium index. In-sample = before 2025-06-01; out-of-sample (OOS) = after.

## Literature reviewed (what the evidence says at our horizons)
| Effect | Source | Our test (rank IC, t-stat in-sample / OOS) | Verdict |
|---|---|---|---|
| Short-term reversal (1–4h) | Wen et al. 2022 (NAJEF); Kitron & Wengrowicz 2026 (90% of Binance pairs reverse at 15m, but the edge is smaller than fees) | −0.026 to −0.032, t ≈ −14 / −12 | Real, **not tradable after fees** (tested) |
| BTC → altcoin lead-lag | Kurihara & Matsumoto 2026 | +0.032 to +0.044 at 1–8h, t ≈ 16 / 13 | Real, **killed by fees** at 1.4×/day turnover |
| 1–4 week momentum | Liu, Tsyvinski & Wu 2022 (J. Finance) | weak; regime-dependent | Works 2026; fails 2023–24 alone |
| Lottery / MAX effect | Grobys & Junttila 2021 (low-MAX beats high-MAX by >1.5%/week) | −0.067 / −0.062 (24h), t ≈ −6 / −4 | Real in ranks; **shorting it loses** (pump tail) |
| Low volatility / low beta | Kwok et al. (J. Empirical Finance); Frazzini & Pedersen 2014 (BAB) | −0.068 / −0.072 (24h) | Same: exploit **long-only** |
| Funding-rate crowding | Presto Labs (cross-sectional) | −0.038 IS (t −4.5), ≈0 OOS | Not robust; unused |
| Market timing (breadth, funding, premium, flow) | various | nothing significant in both periods | Unused, so we stay close to beta-neutral |
| Intraday seasonality | Baur et al. (no persistent pattern) | not pursued | Unused |
| Cost-aware rebalancing | Gârleanu & Pedersen 2013 (trade partially toward the aim) | implemented as 3 overlapping tranches | Used |
| Backtest overfitting | Bailey & López de Prado 2014 (deflated Sharpe) | few variants, IS/OOS split, live/research parity test | Used |

**Key lesson: IC ≠ P&L.** High-volatility and lottery-like coins have *lower median*
but *higher mean* returns, because rare pumps dominate. A long/short low-risk portfolio
therefore has a significant negative IC **and** loses money (Sharpe −1.1). The anomaly is
harvested safely by **owning** low-risk coins and by shorting only *calm* losers.

## Portfolio results: fees included, 14-day windows, tradeable universe, live-style tranching
| Strategy | Sharpe 2023–26 | Return | Max DD | 2023 | 2024 | 2025 | 2026 | OOS windows > 0 | OOS median composite |
|---|---|---|---|---|---|---|---|---|---|
| **v2 ensemble (LIVE)** | **0.73** | +39% | **17.4%** | 0.73 | 0.82 | 0.38 | 1.01 | **65%** | 2.57 |
| v1 blend (previous) | 0.71 | +44% | 22.6% | 0.58 | 0.55 | 0.14 | 1.63 | 59% | 3.69 |
| new sleeves only | 0.56 | +28% | 17.4% | 0.68 | 0.92 | 0.54 | −0.09 | 55% | 1.50 |
| low-risk L/S (rejected) | −1.08 | −58% | 62% | | | | | 42% | −1.94 |
| catch-up overlay, 8h (rejected) | −3.21 | −91% | 91% | | | | | 22% | −5.55 |

Last 60 days: ensemble Sharpe 3.80, +10.3%, max DD 4.0%. Last 180 days: Sharpe 1.83, +12.8%, max DD 7.1%.

### Why the ensemble
- Highest full-period Sharpe and lowest drawdown; **positive in every calendar year**.
- Combines a factor that works in the current regime (momentum) with one that is regime-robust
  (low-risk long), so we do not bet the contest on one regime continuing.
- Sleeves net against each other before trading, which cuts turnover (0.18 of equity per day).

### Verification
`python -m research.parity_check` recomputes each sleeve with the live code
(`bot/strategy/signals.py::ensemble_weights`) at random dates and compares it with the research
backtester: **max weight difference 8e-17 (identical)**.

Reproduce: `python -m research.download_full && python -m research.signal_lab && python -m research.xs_backtest`


## v2.1: breadth, spreads, overlay and scoring (overnight study, 2026-10-10)

**Risk overlay** (`research/overlay_study.py`, live logic replayed on every 14-day window):
the original tight overlay (CPPI 96% floor, 1.5–4.5% brake, 24h limit) **reduced** the
OOS median composite from +2.67 to −0.78. It de-risked after small dips and missed the
rebounds (whipsaw). Replaced by a loose 2.5–7% drawdown brake (OOS +2.70, p95 drawdown
4.9% vs 5.1% with no overlay).

**Breadth** (`research/breadth_check.py`): Sharpe rises monotonically with universe size
and is flat across 3/4/5 coins per side, as Grinold's fundamental law predicts
(IR ∝ IC·√breadth). Without PEPE/SHIB:

| Universe | Sharpe (n=3/4/5) | Return (n=4) | Max DD | OOS windows > 0 | OOS median composite |
|---|---|---|---|---|---|
| 15 | 0.86 / 0.89 / 0.87 | +51% | 18.2% | 62% | 3.25 |
| 20 | 1.11 / 1.14 / 1.07 | +72% | 17.3% | 64% | 2.07 |
| **25 (LIVE)** | **1.29 / 1.27 / 1.22** | **+84%** | **16.9%** | **67%** | **4.02** |
| 29 | 1.39 / 1.44 / 1.37 | +101% | 16.8% | 68% | 3.80 |

Calendar-year Sharpe at 25 coins: 2023 1.02, 2024 1.40, 2025 1.39, 2026 1.21.
**PEPE and SHIB** are excluded: their tick sizes create 18–25 bp spreads on Roostoo, and
removing them improved every universe size. We use 25 rather than all 29 because the coin
list contains only today's survivors (**survivorship bias**), and that bias is largest for
the smallest coins.

**Execution timing** (rejected): conditioning rebalance timing on 1–4h reversal or BTC
catch-up moves fills by only 1–2 bp, worth less than 0.1% over the contest.

**Scoring and exposure** (`research/score_mc.py`, 976 eight-day OOS stretches after 6 flat
days): the median composite is ~1.58 for 0.75×–1.6× exposure (the ratios are
scale-invariant). More exposure raises P(return > 2%) from 19% to 24% but also raises
P(loss > 3%) from 3% to 7.5%. Exposure stays at 1.0× unless the leaderboard shows we are
below the top-20 cutoff.

**Tail risk and stops** (`research/tail_study.py`): the ensemble's worst hour since 2023 was
−1.8% (equal-weight market −11.7% in the same hour). In the 2025-10-10/11 crash window the
ensemble lost −2.3% while the market lost −20.6% and BTC −9.4%. Average net exposure is
+0.31 and gross 0.64. Per-coin trailing stops reduced Sharpe in **both** periods (none 1.27;
6–15% stops 0.75; 3–8% 0.74; 10–25% 0.94) without lowering max drawdown, so they are disabled.
Portfolio-level protection remains the 2.5–7% drawdown brake.

**Stress test on unseen data** (`research/stress_test.py`, 2021-01 → 2022-12; no data from this
period was used to design anything): the ensemble returned **+19.8% (Sharpe 0.70) while BTC
fell −49.2%**. Across 98 fourteen-day windows: median return +0.57%, 56% positive, median max
drawdown 2.9%, median composite 2.73, in line with the main out-of-sample results.

| Crash | Ensemble | Equal-weight market | BTC |
|---|---|---|---|
| LUNA (2022-05-07..13) | −6.7% | −23.2% | −18.8% |
| 3AC/Celsius (2022-06-10..19) | −4.2% | −21.2% | −35.9% |
| FTX (2022-11-06..10) | −1.5% | −18.8% | −18.0% |

Calendar-year Sharpe: 2021 2.81, **2022 −1.42**, 2023 1.47, 2024 1.26, 2025 1.39, 2026 0.94.
The known weakness is a *prolonged* bear market, through the net long tilt (+0.31) of the two
long-only sleeves.

**Residual momentum** (Blitz, Huij & Martens 2011; strip BTC beta from returns): it looked
better on 2023–26 (Sharpe 1.27 → 1.53, both periods' composites up) but was **worse on the
unseen 2021–22 data** (median 14-day composite 2.73 → 1.59). **Not adopted.** Calendar-year
Sharpe ratios have a standard error of about ±1, so "better every year" in the design period
was weak evidence.

**How much of our Sharpe is luck?** (`research/deflated_sharpe.py`, Bailey & López de Prado.)
Live ensemble over 1,345 days: annual Sharpe 1.27, skew 0.03, kurtosis 5.0.
- Probabilistic Sharpe Ratio: **P(true Sharpe > 0) = 99.2%**
- Deflated Sharpe Ratio, which corrects for the best-of-N trials we ran:
  **71% (N = 42 recorded trials), 64% (N = 80), 57% (N = 150)**

We are confident the edge is real. Its magnitude is probably overstated by selection, so we
expect a live Sharpe below the backtest's 1.27.

**Overlay re-validated at the live 25-coin config:** no overlay gives a median 14-day composite
of 2.32 IS / 5.00 OOS. The 2.5–7% brake gives 1.40 / 4.21 and the old tight overlay −2.19 / 0.94.
A **catastrophe-only 6–12% brake** gives 2.32 / 5.00 (same as none) and lowers the worst
14-day drawdown from 10.2% to 9.5% IS and from 9.1% to 8.8% OOS. **Adopted.** End-of-contest
taper: IS favours it (1.35 vs 1.22), OOS does not (2.86 vs 3.28), so it is unchanged.
Exposure at 25 coins: the median composite is flat at ~3.3 for 0.75×–1.6×; P(return > 2%)
is 21% at 1.0× and 27% at 1.33×; P(loss > 3%) is 3.5% and 5.8%.

**Execution deadband** (`research/deadband_study.py`): the live executor skips trades under 2%
of equity, so small targets are never opened (average |held − target| is 13% of equity). Against
trading every change: Sharpe 1.21 vs 1.27, IS composite 4.64 vs 1.84, OOS 3.00 vs 4.02. The
evidence is mixed across periods, so the deadband is unchanged (it also cuts turnover 0.196 → 0.138).

**Single-name and short-squeeze risk:** a Roostoo short can lose up to its whole collateral, so we
measured the worst historical single-coin days. The worst short day cost **−2.1% of equity** (XLM,
2023-07-13, the XRP-ruling pump), then TRX −1.8% (2024-12-03). The worst long day was −2.0%
(BNB). The largest short weight ever was 10%, and 95% of short weights were ≤ 5.2%. The worst
full short-book day was −3.3%. Inverse-volatility sizing, the 30% cap and four-sleeve averaging
keep single-name blow-ups to about 2% of equity.

**Volatility-managed scaling** (Moreira & Muir 2017; Barroso & Santa-Clara 2015), with the book
scaled daily by target ÷ realised strategy volatility (`research/vol_managed.py`, 2021–2026):

| Variant | Full Sharpe | Max DD | 2022 Sharpe | Median 14d composite (2021–22 / IS / OOS) |
|---|---|---|---|---|
| none (live) | **1.08** | **28.3%** | −1.42 | **2.73 / 2.84** / 4.00 |
| 7d lookback, 0.5–1.5× | 0.73 | 37.0% | −1.96 | 2.16 / 1.96 / 4.59 |
| 14d lookback, 0.5–1.5× | 0.92 | 35.2% | −1.88 | 2.10 / 2.92 / 4.54 |
| 7d, de-risk only (0.5–1.0×) | 1.00 | 27.5% | −1.56 | 2.63 / 2.31 / 4.65 |

Rejected: the sleeves are already volatility-targeted ex ante, and re-scaling on realised
volatility mostly adds noise (worse Sharpe and worse 2022).

**Leaderboard decision table** (`research/risk_table.py`; 2,675 historical 7.5-day stretches of the
live ensemble, fees included). Probability that our final return clears a given top-20 cutoff:

| Exposure | ≥ 0% | ≥ 1% | ≥ 2% | ≥ 3% | ≥ 5% | P(loss > 3%) | Median composite |
|---|---|---|---|---|---|---|---|
| 0.75× | 55% | 27% | 12% | 5% | 1% | 1.1% | 2.12 |
| 1.0× (live) | 55% | 32% | 18% | 9% | 3% | 3.1% | 2.11 |
| 1.33× | 55% | 36% | 23% | 15% | 5% | 6.7% | 2.11 |
| 1.6× | 55% | 37% | 24% | 15% | 5% | 8.1% | 2.11 |

The ratios do not depend on exposure, so the median composite is flat. Exposure only trades
the chance of clearing a positive cutoff against loss risk, and above 1.33× the 95% gross cap
binds. Rule: cutoff ≤ 0% → 1.0×; cutoff around 1–3% → 1.33× (`target_daily_vol = 0.016`);
cutoff ≥ 5% → out of reach for this strategy at any responsible exposure.

**Plan B for a high top-20 cutoff** (`research/plan_b.py`, 7.5-day stretches 2023–26):

| Mix @ exposure | P(≥3%) | P(≥5%) | P(≥8%) | P(loss > 5%) | Median composite |
|---|---|---|---|---|---|
| Live ensemble @ 1.0× | 9% | 3% | 0% | 0.6% | 2.11 |
| Live ensemble @ 1.33× | 15% | 5% | 1% | 1.1% | 2.11 |
| Long-only momentum + low-risk @ 1.33× | 26% | 15% | 7% | 9.8% | 1.90 |
| Long-only momentum @ 1.33× | 27% | 16% | 7% | 9.2% | 1.18 |

Plan B is `sleeve_weights = (0, 0.5, 0, 0.5)` and `target_daily_vol = 0.016`. It roughly triples
P(return ≥ 5%) for a modest composite cost, but it is net long the market. Use it only if
the leaderboard requires it.

**Cost sensitivity** (live ensemble, 2023–26; turnover 0.196× equity per day, so a 0.1% fee costs
about 7.2% a year):

| Cost per unit traded | Sharpe (full / IS / OOS) | Return | Median 14d composite (IS / OOS) |
|---|---|---|---|
| 0% | 1.78 / 1.37 / 2.47 | +140% | 3.45 / 5.15 |
| 0.05% (all maker) | 1.52 / 1.10 / 2.22 | +110% | 2.62 / 4.42 |
| 0.075% (realistic mix) | 1.40 / 0.97 / 2.09 | +97% | 2.23 / 4.22 |
| **0.10% (reported, all taker)** | **1.27 / 0.84 / 1.97** | **+84%** | **1.84 / 4.02** |
| 0.15% | 1.01 / 0.58 / 1.72 | +62% | 1.19 / 3.64 |
| 0.20% | 0.75 / 0.32 / 1.46 | +42% | 0.62 / 3.22 |
| 0.30% | 0.23 / −0.21 / 0.96 | +9% | −0.85 / 1.74 |

The edge survives twice the taker fee, and break-even is around 0.35%.

**Alpha decay: why a ~3-day holding period.** This is the forward return of each day's target
book, gross of fees, over different holding horizons (bps):

| Horizon | Total IS / OOS | Per day IS / OOS |
|---|---|---|
| 6h | 0.2 / 1.5 | 0.7 / 5.8 |
| 1 day | 3.3 / 8.7 | 3.3 / 8.7 |
| 3 days | 10.1 / 21.0 | 3.4 / 7.0 |
| 7 days | 27.4 / 28.2 | 3.9 / 4.0 |
| 14 days | 61.1 / 30.4 | 4.4 / 2.2 |

The signal keeps paying for one to two weeks. Out of sample, the per-day payoff is front-loaded
(about 7–9 bps a day over the first three days) and fades afterwards. Re-aiming a third of the
book each day (a ~3-day hold) captures the fresh alpha while keeping fees at ~0.2× equity a day.

**Capacity:** our order size divided by the coin's trailing 24h Binance volume, per traded
coin-rebalance.

| Fund size | Median | 95th percentile | Max |
|---|---|---|---|
| $100k (contest) | 0.0015% | 0.02% | 0.27% |
| $1M | 0.015% | 0.21% | 2.7% |
| $10M | 0.15% | 2.1% | 27% |
| $100M | 1.5% | 21% | 272% |

Market impact is negligible at contest size and small up to a few million dollars. From about
$5–10M the smallest coins (ZEC, XLM, PENDLE, ICP, CRV: $5–12M daily volume) would need
volume-weighted position limits.
