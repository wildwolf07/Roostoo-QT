# Presentation outline (10 slides, ~8 minutes)

Audience: the finale judges (Susquehanna and industry). They reward probabilistic thinking, rigour,
honesty about uncertainty and risk discipline, not a lucky P&L. Every slide makes one claim
and shows the evidence for it.

---

### 1. Title: "Measure, don't guess: a risk-first crypto ensemble"
Team150-negExp · Roostoo APAC Quant Hackathon · repo link
One-line result: *2021–26: the same return as BTC at a quarter of the volatility (Sharpe 1.07 vs 0.53, max
drawdown 28% vs 77%); out-of-sample Sharpe 1.83 while BTC fell; live: positive with a sub-0.5% drawdown*

### 2. The problem, framed by the scoring function
- Screening = 50% portfolio ratios (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar) + 50% strategy repository.
- 70% of the weight punishes downside, and Calmar's denominator is max drawdown.
- Implication: optimise for a **smooth, positive** curve. Fees (0.1% taker / 0.05% maker)
  make turnover the enemy.

### 3. Our first idea failed, and we found out why
- v0 (fast hourly trend + BTC regime gate): lost money in 69 two-week backtests, with fees ≈ losses.
- Diagnosis via rank IC: short horizons **mean-revert**; 7–14 day relative strength **persists**.
- Lesson: we measure before we build. (Show the IC table: lookback × horizon.)

### 4. Literature → hypotheses → our data
Table: effect, source, our IC (in-sample / out-of-sample), verdict. Momentum (Liu–Tsyvinski–Wu),
lottery/MAX (Grobys–Junttila), low-volatility (Kwok et al.), BAB (Frazzini–Pedersen),
reversal, lead-lag, funding, seasonality. Strict split: 2023-01–2025-05 vs 2025-06–2026-10.

### 5. The key insight: IC ≠ P&L
- Shorting lottery coins has t ≈ −6 IC **and** Sharpe −1.1.
- Why: lower median, higher mean. Rare pumps dominate a short book.
- Design response: own low-risk coins long-only; short only *calm* losers.

### 6. The strategy: four sleeves, one book
Diagram: momentum L/S (beta-neutral) · momentum long · filtered momentum L/S · low-risk long,
each vol-targeted to 1.2% a day and averaged over 3 daily tranches (Gârleanu–Pedersen-style
partial trading). Sleeve correlations (momentum L/S vs low-risk long −0.19).
Ablation: removing any sleeve hurts one test period.

### 7. Robustness, not a lucky backtest
- Plateau check: the live config ranks 5/15 in a one-at-a-time grid.
- Breadth chart (Grinold): Sharpe 0.89 → 1.27 from 15 → 25 coins, flat across 3/4/5 per side.
- Unseen 2021–22: +19.8% while BTC fell −49%.
- Parity test: live code equals research code (8e-17).

### 8. Risk management that we *tested*
- Crash chart: LUNA −6.7% vs market −23%; FTX −1.5% vs −19%; Oct-2025 −2.3% vs −21%.
- What we removed because the data said so: tight CPPI and drawdown brakes (whipsaw: OOS median
  14-day composite 0.94 vs 5.00 with no overlay) and per-coin stops (Sharpe 1.27 → 0.75).
- What stays: a catastrophe-only 6–12% drawdown brake (free insurance: same median score as none,
  smaller worst case), position caps, no leverage, and a taper over the last 1.5 days.

### 8b. Playing the scoring rule: the endgame lock-in
- The score is a *ratio* over a fixed window. Once a gain is banked, more risk grows the
  denominators faster than the numerators, so the best policy cuts risk when ahead and keeps it
  when behind (tournament theory: Brown–Harlow–Starks 1996, Browne 1999).
- Rule committed in code on Oct 10, refined on Oct 11 with the real leaderboard: exposure 1× → 0.075× as banked return goes 0 → +0.25%, next to the closed-form optimum.
- Evidence (5,350 historical stretches, four readings of the formula): median composite
  10.6 → 30.0, P(loss) 22% → 8%, for −0.05% of median return. On the real India leaderboard:
  P(top 5 by composite) 62% → 93–94%, P(#1) 9% → 27–32%.

### 9. Live results vs expectation
- Live equity curve plus daily returns (`scripts/daily_report.py`).
- Live vs backtest: fills (maker share), fees, tracking error, exposure.
- Honest note on what we would change, and on the late start (live from Oct 10).

### 10. Engineering and what's next
- Architecture: stateless restarts, rate limiter, audit log (every order with its reason),
  maker-first execution, systemd on EC2, commit-only deploys.
- Decision log (DECISIONS.md): 6 evidence-based changes and 10 rejected ideas, with numbers.
- Next: a bear-market contingency (BTC < 50-day average filter: better long-run Sharpe, worse
  median 14-day score), more breadth, intraday execution via maker queues.

---
Appendix: full IC table, robustness grid, Monte Carlo of exposure vs P(top-20), overlay study.
