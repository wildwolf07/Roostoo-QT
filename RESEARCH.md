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
