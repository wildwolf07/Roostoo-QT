# Roostoo-QT: a risk-first autonomous crypto trading bot

[![tests](https://github.com/wildwolf07/Roostoo-QT/actions/workflows/tests.yml/badge.svg)](https://github.com/wildwolf07/Roostoo-QT/actions/workflows/tests.yml)

**Team150-negExp (MSU)** · APAC Quant Trading Hackathon (Roostoo × Susquehanna × AWS) · India region

A fully autonomous bot that trades a hedged, diversified crypto book on the Roostoo mock exchange.
Once a day it ranks the 25 most liquid coins on medium-term momentum and on risk. It holds an
equal-weight **ensemble of four long/short and long-only sleeves**, sizes positions by volatility
and trades maker-first to keep costs low. The contest is scored on risk-adjusted ratios (Sortino,
Sharpe, Calmar), so everything is built for a **smooth, positive equity curve with small
drawdowns**, not for maximum return.

**Contents:** [1 Summary](#1-two-minute-summary) · [2 Live forward test](#2-live-forward-test) ·
[3 Strategy](#3-strategy) · [4 Robustness evidence](#4-evidence-that-the-strategy-is-robust) ·
[5 Viability in real markets](#5-is-it-viable-in-a-real-market) · [6 Risk management](#6-risk-management) ·
[7 Engine](#7-trading-engine-and-architecture) · [8 Methodology and reproduction](#8-backtesting-and-forward-testing-methodology) ·
[9 Setup](#9-setup-and-running) · [10 Repository map](#10-repository-map) · [11 Compliance](#11-compliance)

---

## 1. Two-minute summary

| Question | Answer |
|---|---|
| What does it trade? | The 25 most liquid of 29 whitelisted coins on Roostoo (by 24h volume), spot long and fully collateralised short, no leverage |
| What is the edge? | **Medium-term momentum** (7–14 day risk-adjusted trend persists at 1–3 day horizons) and the **low-risk anomaly** (low-volatility, low-lottery, low-beta coins earn better risk-adjusted returns), both documented in the literature and re-tested on our own data |
| How is it built? | Four sleeves: momentum long/short (beta-neutral), momentum long-only, filtered momentum long/short, low-risk long-only. Averaged over 3 daily tranches (about a 3-day hold), volatility-targeted, max 30% per coin |
| How does it trade? | One rebalance a day (00:01 UTC). Limit orders at the touch first (0.05% maker fee), market fallback after 3 minutes. Turnover about 0.15–0.2× equity a day |
| Does it work out of sample? | Yes. +41% (Sharpe 1.85) in the 2025–26 out-of-sample period while BTC fell 21%; +20% in the **never-used 2021–22 bear market** while BTC fell 54% |
| How does it behave in crashes? | LUNA −6.5% (market −30%), FTX −1.5% (market −22%), Oct-2025 cascade −2.0% (market −20%) |
| Live? | Trading the competition account since 2026-10-09. Positive with a max drawdown under 0.5% (section 2) |
| Can it run with real money? | Yes, with stated limits: costs, capacity of ~$5–10M, and how shorts would be financed (section 5) |

Headline backtest (live configuration, every fill charged the 0.1% taker fee; full tables in
[`results/backtest/SUMMARY.md`](results/backtest/SUMMARY.md)):

| Period | Strategy | BTC | Equal-weight market |
|---|---|---|---|
| 2021-02 → 2022-12 (**never used for design**) | **+19.8%**, Sharpe 0.70, max DD 28.3% | −54.1%, max DD 77.2% | −12.5%, max DD 82.6% |
| 2023-01 → 2025-05 (in-sample) | +35.4%, Sharpe 0.96, max DD 16.9% | +533%, max DD 32.3% | +278%, max DD 63.6% |
| 2025-06 → 2026-10 (**out-of-sample**) | **+41.2%, Sharpe 1.85**, max DD 14.7% | −21.0%, max DD 53.7% | −15.2%, max DD 64.8% |
| Full 2021-02 → 2026-10 | +128.9%, **Sharpe 1.08**, max DD 28.3% | +129.2%, Sharpe 0.54, max DD 77.2% | +178.8%, Sharpe 0.63, max DD 82.6% |

Over the full sample the strategy matches BTC's return with **double the Sharpe ratio and about a
third of the drawdown**. It lags in strong bull markets (2023–24), because about half the book is
hedged. That is the price of its crash behaviour.

![Strategy vs BTC](docs/img/equity.svg)

---

## 2. Live forward test

The bot went live on the competition account on **2026-10-09 21:51 UTC**. The official contest
window is Oct 4 12:00 → Oct 18 12:00 UTC; before we went live the account was flat cash.

- **As of Oct 12:** about **+1.0%** on the Roostoo leaderboard, with a **max drawdown of 0.46%**
  (bot log). For comparison, the backtest's median 14-day max drawdown is 2.4–2.9%.
- On Oct 11 the market dipped overnight and then rallied. On the evening dip, our hedged book
  rose while long-only books fell. That is the long/short sleeves doing their job.
- Every order, decision and API call is in the bot's SQLite audit log. The day-by-day export
  (equity, exposure, orders, fills, fees, maker share, API success rate) is in
  [`results/forward_test/`](results/forward_test/), produced by `scripts/export_live.py`.
- Before going live, every release was dry-run on the Roostoo **test account** with the same code.

We expect live performance to come in **below** the backtest. The deflated Sharpe ratio (section 4)
says part of the backtest's edge is selection luck. Ten days of live data is too short to measure
the edge; what it does show is that the engine and risk controls behave as designed.

---

## 3. Strategy

### 3.1 Intuition
1. **Trends persist for days, reversals dominate hours.** Over 7–14 days, winners keep winning
   for the next 1–3 days (momentum), while over 1–24 hours prices mean-revert. Our first,
   fast design lost money for exactly that reason (section 4). So we trade the slow effect.
2. **Calm coins are underpriced.** Lottery-like, high-volatility, high-beta coins are overpriced on
   average. Owning the calm ones earns better risk-adjusted returns. Shorting the lottery coins
   does *not* pay, because rare pumps dominate a short book. So that sleeve is long-only.
3. **Different sleeves win in different regimes.** Momentum shines in trends, while low-risk and the
   beta-neutral sleeves hold up in sell-offs. An equal-weight ensemble was positive in every year
   from 2023 to 2026 and has a much smaller drawdown than any single sleeve.

### 3.2 Signals (hourly bars, computed identically in research and live: `bot/strategy/signals.py`)
- `mom` = mean of the 168h and 336h log returns, each divided by `vol72 · √L` (a risk-adjusted trend)
- `vol72` = std of hourly log returns over 72h · `max24` = largest hourly return in the last 24h (a lottery proxy)
- `beta` = 336h rolling beta of hourly returns to BTC
- Each feature is z-scored across the universe and clipped at ±3.

### 3.3 Sleeves (4 coins per side, inverse-volatility weights)
| Sleeve | Long | Short | Purpose |
|---|---|---|---|
| 1. Momentum L/S | top-4 `mom` | bottom-4 `mom`, scaled so the short leg's BTC beta equals the long leg's | trend premium with no market beta |
| 2. Momentum long | top-4 `mom` | — | trend premium plus a modest long tilt |
| 3. Filtered momentum L/S | top-4 `mom` among coins with `max24` rank ≤ 70% | bottom-4 `mom` among coins with `vol72` rank ≤ 60% | no lottery longs, no pump-prone shorts |
| 4. Low-risk long | top-4 of −z(`vol72`) − z(`max24`) − z(`beta`) | — | low-vol / lottery / betting-against-beta anomalies |

### 3.4 Portfolio construction
- **Ensemble:** the mean of the four sleeves' target weights. Sleeves are **netted before trading**,
  so opposite views on a coin cancel instead of paying fees twice.
- **Tranching:** the target is the average of the targets computed now, 24h ago and 48h ago. Each
  tranche is held about 3 days, so a third of the book is re-aimed each day. This acts like a decay
  filter.
- **Sizing:** each sleeve is scaled to 1.2% expected daily portfolio volatility. Max 30% of equity
  per coin, gross exposure ≤ 95%, shorts fully collateralised (Roostoo `/v6`), no leverage.
- **Universe:** the top 25 of 29 whitelisted coins by Roostoo 24h volume, re-selected daily.
  PEPE and SHIB are excluded for 18–25 bp spreads.

### 3.5 Execution
Reduce first (SELL / SHORT_CLOSE), then add (BUY / SHORT_OPEN). Spot orders go out as LIMIT at the
best bid or ask, which pays the maker fee. After 3 minutes the remainder is re-planned from fresh
exchange state and sent at market. Gaps smaller than a deadband are not traded: 2% of equity for a
full book, and $50 for a small book (section 6).

### 3.6 Parameters and why
| Parameter | Value | Evidence |
|---|---|---|
| Momentum lookbacks | 168h, 336h | positive rank IC at 1–3 day horizons in- and out-of-sample; 1–24h lookbacks mean-revert (IC t ≈ −14) |
| Holding period | ~3 days (3 daily tranches) | the alpha-decay curve is front-loaded over the first 3 days; a shorter hold pays more fees |
| Vol target | 1.2%/day | best 14-day composite of 1.2 / 1.6 / 2.0% |
| Coins per side | 4 | 3, 4 and 5 all within noise; we chose the middle of the plateau |
| Universe size | 25 | Sharpe rises with breadth (15 → 0.89, 20 → 1.14, 25 → 1.27), as Grinold's fundamental law predicts |

---

## 4. Evidence that the strategy is robust

All numbers are reproducible from the code in `research/`. Raw outputs are in
[`results/backtest/`](results/backtest/).

**4.1 Periods and an unseen bear market.** Design used 2023-01 → 2025-05 only. 2025-06 → 2026-10 is
out-of-sample, and **2021–22 (the LUNA, 3AC and FTX collapses) was never looked at during design**.
The strategy is positive in all three periods (table in section 1).

**4.2 The contest's own horizon.** We scored every 14-day window, in weekly steps, with the
competition's composite (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar):

| Period | Windows | Median return | % positive | Median max DD | 95th pct max DD | Median composite |
|---|---|---|---|---|---|---|
| 2021–22 unseen | 100 | +0.57% | 56% | 2.9% | 6.3% | 2.73 |
| 2023–25 in-sample | 126 | +0.51% | 61% | 2.6% | 5.8% | 2.84 |
| 2025–26 out-of-sample | 69 | +0.70% | 64% | 2.4% | 5.1% | 4.00 |

**4.3 Crashes** (window returns; [`crash_events.csv`](results/backtest/crash_events.csv)):

| Event | Strategy | BTC | Equal-weight market |
|---|---|---|---|
| LUNA collapse (May 2022) | −6.5% | −18.6% | −30.1% |
| 3AC / Celsius (Jun 2022) | −4.1% | −30.9% | −26.1% |
| FTX (Nov 2022) | −1.5% | −17.5% | −22.4% |
| Oct-10 2025 liquidation cascade | −2.0% | −9.1% | −20.4% |

![Crash protection](docs/img/crashes.svg)

**4.4 Calendar years.** 2021 +48.5%, **2022 −19.6%**, 2023 +21.8%, 2024 +18.5%, 2025 +19.5%,
2026 YTD +10.3%. 2022 is the known weakness: a long, grinding bear market hurts the two long-only
sleeves. We tested a BTC-trend filter that fixes 2022 (full Sharpe 1.08 → 1.55). It *lowers* the
median 14-day score, because it lags rebounds, so it stays a documented contingency
([DECISIONS.md](DECISIONS.md)).

**4.5 Statistics and overfitting control** (2023–26 research panel)
- Probabilistic Sharpe ratio 99.2%. **Deflated Sharpe ratio 64–71%** after correcting for every
  variant we tried (about 40–80), plus skew and fat tails (Bailey & López de Prado).
- Stationary block bootstrap: Sharpe 1.28, **95% CI [0.19, 2.34]**, P(Sharpe ≤ 0) = 1.1%. The edge
  is very likely positive, but its size is uncertain.
- Parameters were chosen from **plateaus, not peaks**: the live configuration ranks 5th of 15 in its
  own grid.
- **Survivorship test:** on a 72-coin point-in-time universe that includes later-delisted coins
  (EOS, FTM, MKR, WAVES, MATIC, RNDR, FTT), the same strategy does *better* (Sharpe 1.55 vs 1.08).
  Our results are not an artefact of today's survivors.
- **Breadth:** Sharpe rises monotonically with universe size (0.89 → 1.14 → 1.27 for 15/20/25 coins).
- **Rejected ideas**, each with its numbers in [DECISIONS.md](DECISIONS.md): fast trend with a
  regime gate (our v0, lost money), short-term reversal and BTC lead-lag (t > 10 but below fees),
  funding-rate signals (in-sample only), low-risk long/short (IC ≠ P&L), per-coin stops (Sharpe
  1.27 → 0.75), tight drawdown overlays (whipsaw), volatility-managed scaling, residual momentum
  (failed 2021–22), a larger whitelist (failed 2021–22).

**4.6 Live = research.** `research/parity_check.py` recomputes every sleeve with the live code at
random historical dates: max weight difference 8e-17. The event-driven backtester
(`backtest/engine.py`) runs the live strategy, risk and order-planning code hour by hour.

![Breadth effect](docs/img/breadth.svg)

---

## 5. Is it viable in a real market?

| Aspect | Assessment |
|---|---|
| **Costs** | Edge survives double the taker fee: Sharpe 1.52 at 0.05%, 1.27 at 0.1%, 0.75 at 0.2%. Break-even is about 0.35% per unit traded, against ~0.1% taker and 1–5 bp spreads on these coins on major venues |
| **Capacity** | At $100k the median order is 0.0015% of the coin's daily volume. At $10M the 95th percentile order reaches ~2% of daily volume in the smallest coins, so without liquidity-weighted sizing the practical limit is ~$5–10M |
| **Latency** | None needed: one rebalance a day, no order-book race, no HFT, market making or arbitrage |
| **Shorts** | Roostoo shorts are free and fully collateralised. On a real venue the short legs would use perpetual futures. Funding has mostly been paid by longs to shorts, so the shorts would usually earn carry, but this is venue-dependent and **not modelled** (conservative) |
| **Data** | Binance public hourly bars only. Four fallback hosts, and cached bars if all fail |
| **Operations** | Restart-safe: state is rebuilt from the exchange every minute. Bounded retries, a daily safety net, a full audit log, systemd auto-restart, commit-only deploys, CI on Python 3.9 and 3.12 |
| **Known risks** | Prolonged bear markets (2022: −19.6%). Momentum crashes in sharp reversals. An edge of uncertain size (bootstrap CI above). Exchange and custody risk on a real venue |
| **Before real capital** | Liquidity-weighted position limits, a funding/borrow cost model, multi-venue execution, the bear-market filter as a switchable regime overlay, quarterly re-validation out of sample |

---

## 6. Risk management

| Control | Rule | Evidence |
|---|---|---|
| Volatility target | gross exposure sized for ~1.2% expected daily portfolio volatility | best composite of 1.2 / 1.6 / 2.0% |
| Concentration | ≤ 30% of equity per coin, 4 coins per side per sleeve, 25-coin universe | worst single coin-day in the backtest: −2.1% of equity |
| Leverage | none; gross ≤ 95%; shorts fully collateralised | — |
| Drawdown brake | catastrophe-only: linear de-risking from 6% to 12% drawdown from peak (to ×0.25) | tighter brakes whipsaw: they cut the median 14-day composite in both periods |
| Per-coin stops | built and tested, **disabled** | every setting lowered Sharpe (1.27 → 0.75 for 6–15%) and did not cut max drawdown |
| **Endgame lock-in** (contest overlay) | from Oct 10: exposure ×1 → ×0.075 as the banked contest return goes 0 → +0.25%; back to full size only if the gain is gone | see below and [docs/ENDGAME.md](docs/ENDGAME.md) |
| Taper | ×0.5 for the final ~36h | — |
| Operational | price sanity check (±3% of ticker), order-size cap, stale orders cancelled on restart, data fallbacks, bounded retries, a 10:00 UTC safety-net trade | unit-tested |

**Why the lock-in.** The judges' ratios are computed over a fixed window. Once a gain is banked,
extra risk grows the denominators (volatility, downside deviation, max drawdown) faster than the
numerators. We derived the optimal exposure in closed form,
k\* = (μ / s²) · (Q / S): the Kelly leverage times the realised variance per unit of banked profit.
We checked it on 5,350 historical stretches under four readings of the formula, and
[docs/ENDGAME.md](docs/ENDGAME.md) has the proof, simulation, audit and literature (Brown, Harlow & Starks
1996; Browne 1999; Basak, Pavlova & Shapiro 2007). It is the evaluation-period version of what
real desks do with P&L-based risk budgets. The **core strategy (sections 3–5) is what we would run
with real capital**. The lock-in is a mandate-specific overlay, set by how this contest is scored.

---

## 7. Trading engine and architecture

```
 every 60 s   Roostoo: ticker + balance + short positions
              └─► portfolio rebuilt from the exchange (never from memory; restart-safe)
                  ├─► equity snapshot → SQLite audit log
                  └─► risk state: drawdown brake, endgame lock-in, taper

 daily        Binance hourly klines (25 most liquid coins, ~500 h of history; cached fallback)
 00:01 UTC    └─► features: momentum · volatility · MAX · beta          (bot/strategy/signals.py)
                  └─► 4 sleeves → equal-weight ensemble → mean of 3 daily tranches
                      └─► executor: reduce first, then add; maker-first LIMIT → 3 min → re-plan → MARKET
                          (retried up to 5×; a 10:00 UTC safety net guarantees a trade every day)
```

| Module | Responsibility |
|---|---|
| `bot/api/roostoo_client.py` | HMAC-SHA256 signing, rate limiter (≤ 20 calls/min vs the 30 limit), retries with backoff, `Success`-flag handling, audit hook |
| `bot/data/market_data.py` | Binance hourly klines with 4 fallback hosts and a cache, ticker parsing, universe selection by 24h volume |
| `bot/strategy/signals.py` | **Pure functions** shared by the live bot and the backtesters: features, sleeves, ensemble, tranching |
| `bot/risk/risk_manager.py` | Drawdown brake, endgame lock-in, taper (CPPI cap, 24h loss limit and trailing stops available but disabled by research) |
| `bot/execution/executor.py` | Targets → orders, precision rounding, deadbands, maker-first with market fallback, long and short legs |
| `bot/storage/db.py` | SQLite audit trail: every API call (with success flag), order (with the signal reason), decision and equity snapshot |
| `bot/main.py` | Autonomous scheduler: minute snapshots, daily rebalance with bounded retries, safety net, persisted state |
| `bot/config.py` | Every tunable in one place, each with the study that set it |

Tech stack: Python 3.9+, `requests`, `numpy`, `pandas`, SQLite, systemd on AWS EC2 (ap-southeast-2).

---

## 8. Backtesting and forward-testing methodology

- **Data:** Binance hourly bars (Roostoo prices are streamed from Binance) for the whitelisted coins,
  2021-01 → 2026-10, plus funding, premium and order-flow data for signal research.
- **Splits:** in-sample 2023-01 → 2025-05, out-of-sample 2025-06 → 2026-10, unseen 2021–22.
- **Contest-shaped scoring:** every 14-day window scored with the competition composite.
- **Costs:** every simulated fill pays the 0.1% taker fee. Live, the limit orders that fill as maker pay
  0.05%; the measured share is in the forward-test export.
  The event-driven engine adds slippage.
- **Two backtesters:** a vectorised research backtester (`research/xs_backtest.py`, fast studies) and
  an hour-by-hour event-driven backtester (`backtest/engine.py`) that runs the **live** strategy,
  risk and order-planning code. The parity test ties both to the live bot.
- **Rule for any change:** it must improve **both** periods, sit on a plateau and be explainable.
  Every change and every rejected idea is in [DECISIONS.md](DECISIONS.md).
- **Forward tests:** dry runs on the Roostoo test account before each release, then the live
  competition account (section 2).

**Reproduce the results**
```bash
python -m research.download_pre && python -m research.download_full   # Binance data 2021 → now
python -m research.make_results          # results/backtest/: SUMMARY.md, equity, years, 14-day windows, crashes
python -m research.signal_lab            # which signals predict returns (rank IC, in/out-of-sample)
python -m research.ablation              # contribution of each sleeve
python -m research.survivorship          # point-in-time universe with delisted coins (needs download_broad)
python -m research.parity_check          # live code == research code
python -m backtest.engine --windows      # event-driven backtest of the live code, 14-day windows
python -m research.endgame --banked 0.01 # contest endgame study (docs/ENDGAME.md)
```
Live forward-test export (on the server, read-only): `python -m scripts.export_live`.

---

## 9. Setup and running

```bash
git clone https://github.com/wildwolf07/Roostoo-QT.git && cd Roostoo-QT
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                     # add API keys; MODE=paper|test|live
python -m unittest tests.test_core       # 29 tests
python -m bot.main --mode paper --once   # one dry-run decision cycle (no orders)
python -m bot.main                       # run continuously (MODE from .env)
```

On AWS EC2 (Session Manager shell):
```bash
sudo bash deploy/setup_ec2.sh https://github.com/wildwolf07/Roostoo-QT.git
sudo nano /opt/roostoo-bot/.env          # MODE=live + competition keys
sudo systemctl enable --now roostoo-bot
```
Every later change is deployed from a commit: `sudo bash /opt/roostoo-bot/deploy/deploy.sh`.
Operations guide: [docs/RUNBOOK.md](docs/RUNBOOK.md).

---

## 10. Repository map

| Path | Contents |
|---|---|
| `bot/` | The live trading bot (section 7) |
| `backtest/` | Event-driven hourly backtester running the live code |
| `research/` | Data download, signal lab, portfolio studies, robustness, statistics, endgame, results generator |
| `results/` | Generated backtest results (`backtest/`) and the live forward-test export (`forward_test/`) |
| `tests/` | 29 unit tests: signing, signals, ensemble, risk, lock-in, order planning, shorts, scheduler, data fallback; CI on Python 3.9 and 3.12 |
| `scripts/` | Read-only daily report, live results export, health check (test key only), decision tools |
| `deploy/` | EC2 setup, systemd unit, commit-based deploy |
| [RESEARCH.md](RESEARCH.md) | The full research notebook: literature, IC tables, every study |
| [DECISIONS.md](DECISIONS.md) | Every live change and rejected idea, with numbers |
| [docs/ENDGAME.md](docs/ENDGAME.md) | Contest-endgame risk: derivation, simulation, audit |
| [docs/JUDGES_QA.md](docs/JUDGES_QA.md) | Hard questions with evidence-backed answers |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Operations: daily check, deploy, rollback |
| [research/AGENDA.md](research/AGENDA.md) | Chronological research log |
| [PLAN.md](PLAN.md) | Our original plan (Oct 3), kept for the record |

---

## 11. Compliance

- All trades are generated by the bot. There are no manual API calls on the competition account;
  even our health check uses the test key.
- Every strategy change is a commit, and the server is only updated from commits (`deploy/deploy.sh`).
- Every order is logged with the signal reason that produced it, and every API request with its
  success or failure status.
- No high-frequency trading, market making, latency arbitrage or leverage. One strategy rebalance
  a day. Limit orders are used only to pay the lower maker fee on our own directional trades.
- The bot trades every contest day (about 10 orders a day even with the small locked-in book, in a
  365-day dry run of the order planner).
  A 10:00 UTC safety net guarantees a trade under any day convention.
- API keys live only in `.env` (gitignored), and a pre-commit hook blocks secrets.
