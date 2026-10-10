# Judges' Q&A preparation

The hardest questions we expect from quant judges, with short, evidence-backed answers. Every
number below is reproducible from `research/` (see RESEARCH.md). Rule for the room: **state the
number, state its uncertainty, say what we would do next.**

---

### 1. "Isn't this just overfitting? You tried a lot of things."
We tracked it. About 40–80 configurations were tested. The **deflated Sharpe ratio**, which
corrects for best-of-N selection, skew and fat tails, gives a 64–71% probability that the true
Sharpe beats the best lucky trial, and the probabilistic Sharpe ratio gives 99% that it is above
zero. We also (a) split in-sample and out-of-sample for every decision, (b) chose plateau
settings rather than peaks (the live config ranks 5/15 in its own grid), and (c) validated on
**2021–22 data that was never used for design**: +19.8% while BTC fell −49%. We expect live
Sharpe to be **lower** than the backtest's 1.27, and we say so in the README.

### 2. "Why should 7–14 day momentum work in crypto?"
It is a documented factor (Liu, Tsyvinski & Wu, *J. Finance* 2022), usually attributed to
gradual information diffusion and attention-driven flows. In our data, rank IC is positive at 1–3
day horizons for 7–14 day lookbacks, while 1–24h lookbacks **mean-revert** (IC −0.03, t ≈ −14),
which is why our first, fast design failed. We hold for about 3 days, which is where the signal
lives and fees don't kill it.

### 3. "Why is the low-risk sleeve long-only? The anomaly is long/short in the literature."
Because **IC ≠ P&L** with fat tails. Shorting high-volatility / lottery-like coins has a
significant negative IC (t ≈ −6), yet the long/short portfolio had Sharpe −1.1. Those coins
have a lower *median* but a higher *mean*: rare pumps dominate a short book (e.g. XLM +60% on
the 2023 XRP ruling). Owning the low-risk coins captures the anomaly without selling lottery
tickets. The literature itself notes shorting constraints (Kwok et al.).

### 4. "What is your market exposure? Is this just beta?"
Average net exposure is +0.31 (5–95%: +0.12 to +0.49) and gross is 0.64. Daily correlation with
the equal-weight market is 0.68. It is not just beta: in the LUNA / 3AC / FTX / Oct-2025 crashes
we lost −6.7% / −4.2% / −1.5% / −2.3% while the market lost −23% / −21% / −19% / −21%, and two
of the four sleeves are beta-neutral long/short.

### 5. "Your 2022 Sharpe is negative. What happens in a long bear market?"
That is the known weakness: the two long-only sleeves carry the net long tilt. We tested a
BTC-below-50-day-average filter. It improved long-run Sharpe (1.08 → 1.55) but **lowered** the
median 14-day composite (3.27 → 1.95), because it lags and misses rebounds. Since the contest is
a two-week window, we kept it as a documented contingency rather than turning it on.

### 6. "Why did you remove stop-losses? Isn't that reckless?"
We measured them. Every per-coin stop setting (3–8%, 6–15%, 10–25%) **lowered** Sharpe in both
periods (1.27 → 0.75 for 6–15%) and did not reduce max drawdown. Stops sell on noise and miss the
recovery. Risk is controlled structurally instead: inverse-volatility sizing, a 30% per-coin cap,
a 95% gross cap, no leverage, four diversified sleeves, and a catastrophe-only 6–12% drawdown
brake. The worst single-coin day in the backtest is −2.1% of equity.

### 7. "How do you handle transaction costs?"
Fees were the main reason v0 failed (≈ the size of its losses). Now: a ~3-day holding period
via 3 daily tranches (turnover ≈ 0.14–0.20× equity per day), a 2% deadband, sleeve netting before
trading, and maker-first limit orders (0.05% vs 0.1%; live maker share ~50%). Backtests charge
the **taker** fee on every fill, which is conservative.

### 8. "How do you know the live bot trades what the backtest tested?"
A **parity test** (`research/parity_check.py`) recomputes every sleeve with the live code at
random historical dates: the max weight difference is 8e-17. Known deviations are documented: the
deadband skips small trades (average tracking error ~13% of equity at 2%; effect on Sharpe
1.27 → 1.21), and fills are at Roostoo's bid/ask, not Binance closes.

### 9. "Why a 25-coin universe?"
Grinold's fundamental law: IR ∝ IC·√breadth. Sharpe rises monotonically with universe size
(15: 0.89, 20: 1.14, 25: 1.27, 29: 1.44) and is flat across 3/4/5 coins per side. We stopped at
25 because of **survivorship bias**: our list is today's coins, and that bias is strongest for the
smallest ones. PEPE and SHIB are excluded for 18–25 bp tick-size spreads.

### 10. "What would you do with more time or capital?"
(a) Real execution research with order-book data (maker queue position, adverse selection);
(b) a survivorship-free universe (include delisted coins); (c) regime-conditional sleeve
weights estimated out of sample; (d) capacity analysis (our sizes are small relative to Binance
volume; the mock exchange has no market impact, so a real deployment needs impact modelling).

### 11. "Why didn't you use ML / LLMs?"
With about 30 assets, a few years of data and weak signals (IC ≈ 0.02–0.07), model complexity
mostly buys overfitting. We prioritised a few economically motivated signals, out-of-sample
validation and costs. The same research pipeline (`signal_lab` → `xs_backtest` → parity) would
evaluate any ML signal the same way.

### 12. "What went wrong?"
- v0 lost money: fast signals, fee-blind. We diagnosed it with IC analysis.
- We started live trading late (Oct 10) and lost 6 days of the window.
- Bugs found and fixed through tests and test-account runs: a short-collateral double count,
  a `.gitignore` rule that hid a source folder, and a scheduler that could skip a day's
  rebalance on a data blip. Each is in the commit history.

### 13. "How did you choose your risk level?"
A Monte Carlo over 2,675 historical 7.5-day stretches. The composite score is invariant to
exposure (the ratios are scale-free). Exposure only changes the chance of clearing the top-20
return cutoff versus loss risk, so we set it from the observed leaderboard cutoff
(`research/risk_table.py`).

### 14. "Is any of this manual?"
No. A single autonomous process under systemd on EC2. Deploys only via committed code
(`deploy/deploy.sh`), every order is logged with the signal reason, and the competition key is
never used outside the bot (even our health check uses the test key).

### 15. "What's your single most important insight?"
**Measure before believing.** Statistically strong signals (reversal t ≈ −14, lead-lag t ≈ 16,
short low-risk t ≈ −6) all **lost money** once costs and fat tails were included. Our edge came
from rejecting most ideas with evidence, and the decision log shows each one.
