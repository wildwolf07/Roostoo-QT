# Regime-Gated Volatility-Targeted Trend Bot — Roostoo APAC Quant Hackathon

**Team150-negExp** · Autonomous crypto trading bot for the Roostoo mock exchange.

> One-line thesis: the competition is scored mostly on *downside-aware* ratios
> (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar), so we built a bot that optimises for a
> **smooth, positive equity curve with small drawdowns**, not for maximum return.

---

## 1. Project overview

| | |
|---|---|
| Style | Directional, medium-frequency (hourly decisions), long + cash |
| Universe | Liquid crypto majors on Roostoo that also trade on Binance (for history) |
| Core idea | Trend-following (time-series momentum), gated by a BTC market regime, sized by volatility targeting, wrapped in automatic drawdown controls |
| Execution | Maker-first limit orders (0.05% fee) with market fallback; deadbands to cut turnover |
| Autonomy | Runs 24/7 on AWS EC2 under systemd; no manual input of any kind |

### Why this strategy
1. **Momentum / trend is one of the most persistent effects in crypto.** We use a
   multi-lookback, volatility-normalised score so no single parameter dominates.
2. **The market factor (BTC) drives most altcoin drawdowns.** A regime gate keeps the
   book mostly in cash when BTC trends down, which is where most losses come from.
3. **Volatility targeting smooths returns.** Scaling exposure to a constant expected
   portfolio volatility directly improves Sharpe and Sortino.
4. **Calmar = return / max drawdown.** Automatic drawdown brakes cap the denominator.
5. **Fees are the silent killer.** A round trip costs 0.1–0.2%; our backtests showed fees
   were the single largest drag, so turnover control is a first-class design goal.

---

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
| `backtest/` | Data download, hourly backtester (same strategy code), 14-day window parameter study |
| `tests/` | Unit tests for signing, signals, risk rules and order planning |
| `deploy/` | EC2 setup, systemd unit, commit-based deploy script |

Tech stack: Python 3.9+, `requests`, `numpy`, `pandas`, SQLite, systemd on AWS EC2 (Sydney).

---

## 3. Strategy explanation

_Section filled in with final parameters and backtest evidence — see below._

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
| Regime gate | BTC below its 72h EMA with the 24h EMA below it → RISK_OFF, exposure ×0 (core only) |
| Volatility spike | BTC 24h vol > 2× its 14-day median → exposure ×0.5 |
| Volatility target | gross exposure sized for ~1.2% expected portfolio daily volatility |
| Position cap | ≤30% of equity per coin; gross ≤95%; no leverage |
| Drawdown brake | linear de-risking from 1.5% to 4.5% drawdown from peak (down to ×0.25) |
| CPPI cap | gross ≤ 15 × (equity − 96% of initial) / equity |
| 24h loss limit | if equity fell ≥1.5% over 24h → exposure ×0.5 |
| Trailing stop | per position: max(3%, min(8%, 2.5 × daily vol)) below high since entry; 6h cooldown |
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

Backtest:
```bash
python -m backtest.data_download --days 540
python -m backtest.engine --windows
python -m backtest.sweep
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
