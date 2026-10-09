# Roostoo-QT — Risk-First Autonomous Crypto Trading Bot

**Team150-negExp** · Autonomous crypto trading bot for the Roostoo mock exchange.

> One-line thesis: the competition is scored mostly on *downside-aware* ratios
> (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar), so we built a bot that optimises for a
> **smooth, positive equity curve with small drawdowns**, not for maximum return.

---

## 1. Project overview

| | |
|---|---|
| Style | Directional, low-turnover: daily rebalance of a long/short book |
| Universe | 25 most liquid of 29 whitelisted coins (by Roostoo 24h volume) |
| Core idea | Equal-weight **ensemble of 4 sleeves**: (1) cross-sectional momentum long/short, beta-neutral; (2) long-only momentum; (3) *filtered* momentum (no lottery-like longs, only calm shorts); (4) low-risk long-only (low volatility / low MAX / low beta). Tranched over 3 days, volatility-targeted, wrapped in automatic drawdown controls |
| Execution | Maker-first limit orders (0.05% fee) with market fallback; deadbands to cut turnover |
| Autonomy | Runs 24/7 on AWS EC2 under systemd; no manual input of any kind |

### Why this strategy (full evidence in [RESEARCH.md](RESEARCH.md); every change and rejected idea in [DECISIONS.md](DECISIONS.md))
1. **Literature first, then our own data.** We reviewed the crypto return-predictability
   literature (momentum, reversal, lottery/MAX, low-volatility, betting-against-beta, funding,
   order flow, lead-lag, seasonality) and tested every effect on 3.8 years of hourly data for
   the 31 coins tradable on Roostoo, with a strict in-sample / out-of-sample split.
2. **What survived costs.** Short-horizon effects (reversal, BTC lead-lag) are statistically
   strong (t > 10) but smaller than fees. Medium-term **momentum** and the **low-risk anomaly**
   survive costs at a ~3-day holding period.
3. **IC is not P&L.** Shorting high-volatility "lottery" coins loses money despite a strongly
   negative IC (rare pumps dominate), so low-risk is harvested **long-only**, and the filtered
   momentum sleeve only shorts *calm* losers.
4. **Diversify across regimes.** Momentum works in the current regime; low-risk works across
   regimes. The equal-weight ensemble had the best Sharpe (0.73), lowest drawdown and was
   positive in **every** year from 2023 to 2026 (fees included).
5. **Fees are the silent killer.** Tranching, deadbands, sleeve netting and maker-first orders
   keep turnover at ~0.18× equity per day.

## 2. Architecture

```
                 ┌────────────────────────── every 60 s ───────────────────────────┐
 Roostoo API ──► │ ticker + balance ─► Portfolio (rebuilt from exchange each loop)  │
                 │                      ├─► equity snapshot (SQLite)                │
                 │                      └─► RiskManager: trailing stops ─► MARKET exit│
                 └──────────────────────────────────────────────────────────────────┘
                 ┌─────────────────────── every rebalance (hourly) ─────────────────┐
 Binance klines ►│ hourly closes ─► market_regime(BTC) ─► momentum_scores           │
                 │   ─► target_weights (inverse-vol, vol target, caps)              │
                 │   ─► RiskManager.exposure_multiplier (DD brake, CPPI, 24h limit) │
                 │   ─► apply_risk ─► Executor (sells → buys, maker-first)          │
                 └──────────────────────────────────────────────────────────────────┘
```

| Module | Responsibility |
|---|---|
| `bot/api/roostoo_client.py` | HMAC-SHA256 signing, rate limiter (≤20 calls/min vs 30 limit), retries with backoff, `Success`-flag handling, audit hook |
| `bot/data/market_data.py` | Binance hourly klines (Roostoo has no OHLCV), ticker parsing, universe selection by 24h volume |
| `bot/strategy/signals.py` | **Pure functions** shared by live bot and backtester: regime, momentum, sizing |
| `bot/risk/risk_manager.py` | Drawdown brake, CPPI cap, 24h loss limit, end-of-contest taper, trailing stops, cooldowns |
| `bot/execution/executor.py` | Targets → orders, precision rounding, deadbands, maker-first with market fallback |
| `bot/storage/db.py` | SQLite audit trail: every API call, order (with reason), decision, equity snapshot |
| `bot/main.py` | Autonomous scheduler loop with crash recovery and persisted state |
| `backtest/` | Event-driven hourly backtester (same strategy code as live), 14-day window parameter study |
| `research/` | 2023→now data download (spot, order flow, funding, premium), signal lab (rank-IC in/out-of-sample), vectorised portfolio backtester, live/research parity check |
| `tests/` | Unit tests for signing, signals, risk rules and order planning |
| `deploy/` | EC2 setup, systemd unit, commit-based deploy script |

Tech stack: Python 3.9+, `requests`, `numpy`, `pandas`, SQLite, systemd on AWS EC2 (Sydney).

---

## 3. Strategy explanation

**Features** (hourly bars, computed identically in research and live):
- `mom` = average of 168h and 336h log returns, each divided by `vol72 × √L` (risk-adjusted trend)
- `vol72` = std of hourly log returns over 72h · `max24` = largest hourly return in 24h (lottery proxy)
- `beta` = 336h rolling beta of hourly returns to BTC

Each feature is z-scored across the 25-coin universe (clipped at ±3).

**Sleeves** (each picks 4 coins per side, inverse-volatility weights, scaled to an expected
portfolio volatility of 1.2% per day, ≤30% per coin):
| Sleeve | Long | Short | Notes |
|---|---|---|---|
| 1. Momentum L/S | top-4 `mom` | bottom-4 `mom` | short leg scaled so its BTC-beta equals the long leg's (beta-neutral) |
| 2. Momentum long | top-4 `mom` | none | carries the trend premium |
| 3. Filtered momentum L/S | top-4 `mom` among coins with `max24` rank ≤ 70% | bottom-4 `mom` among coins with `vol72` rank ≤ 60% | avoids lottery longs and pump-prone shorts |
| 4. Low-risk long | top-4 of −z(`vol72`) − z(`max24`) − z(`beta`) | none | lottery / low-vol / BAB anomalies |

**Combination and timing.** Target = mean of the 4 sleeves, averaged over targets computed
now, 24h ago and 48h ago (3 tranches, each held about 3 days). Rebalanced daily at 00:00 UTC.
Gaps below 2% of equity are skipped. Shorts use Roostoo `/v6` (fully collateralised, no leverage).

**Entry / exit.** A coin enters or leaves as its sleeve membership changes. The per-position
trailing stop exits immediately (with a 6h cooldown).

| Key parameter | Value | Why |
|---|---|---|
| Momentum lookbacks | 168h, 336h | Positive IC at 1–3 day horizons; short lookbacks mean-revert |
| Holding / rebalance | ~3 days via 3 daily tranches | Turnover low enough to beat fees; trades every day |
| Vol target | 1.2% / day | Best composite of 1.2 / 1.6 / 2.0% in tests |
| Coins per side | 4 | 3 and 5 tested; 4 is the robust middle |
| Universe | top-25 liquid of 29 | Breadth: Sharpe 0.89 (15 coins) → 1.27 (25); PEPE/SHIB excluded (18–25 bp spreads) |

## 4. Fee handling

- Maker-first: buy LIMIT at best bid, sell LIMIT at best ask → 0.05% instead of 0.1%.
  Unfilled orders are cancelled after 3 minutes and the remainder is re-planned from
  fresh exchange state as a MARKET order.
- Stops and emergency de-risking use MARKET orders (certainty of exit > fee saving).
- Deadband: trades smaller than a set fraction of equity are skipped.
- The backtester charges the full taker fee (0.1%) plus slippage on every fill, so
  reported results are conservative.

## 5. Risk management

| Control | Rule |
|---|---|
| Regime gate (available, off) | BTC trend filter on the long sleeve; disabled because it added no value in testing (RESEARCH.md §2) |
| Volatility target | gross exposure sized for ~1.2% expected portfolio daily volatility |
| Position cap | ≤30% of equity per coin; gross ≤95%; no leverage |
| Drawdown brake | linear de-risking from 2.5% to 7% drawdown from peak (down to ×0.25) |
| Trailing stop | available but **disabled**: lowered Sharpe in both periods (RESEARCH.md, tail study) |
| Taper | final ~36h of the contest → exposure ×0.5 |
| Operational | stale-data skip, price sanity check (±3% of ticker), order-size cap, state rebuilt from exchange every loop |

## 6. Setup and running

```bash
git clone <this repo> && cd <repo>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add API keys; MODE=paper|test|live
python -m unittest tests.test_core
python -m bot.main --mode paper --once   # one dry-run decision cycle
python -m bot.main                       # run continuously (MODE from .env)
```

Research and backtests:
```bash
python -m research.download_full        # 2023 -> now, ~30 coins (spot + funding + premium)
python -m research.signal_lab           # which signals predict returns (IC, in/out-of-sample)
python -m research.xs_backtest          # portfolio variants, fees included, 14-day windows
python -m research.parity_check         # live code == research code
```

Deploy on EC2 (Session Manager shell):
```bash
sudo bash deploy/setup_ec2.sh https://github.com/<org>/<repo>.git
sudo nano /opt/roostoo-bot/.env      # MODE=live + competition keys
sudo systemctl enable --now roostoo-bot
```
Every later change is deployed from a commit: `sudo bash /opt/roostoo-bot/deploy/deploy.sh`.
Service restarts happen only to load newly committed code.

## 7. Compliance

- All trades are generated by the bot; no manual API calls on the competition account.
- Every order is logged with the signal reason that produced it (`orders.reason`).
- API keys live only in `.env` (gitignored); a pre-commit hook blocks secrets.
