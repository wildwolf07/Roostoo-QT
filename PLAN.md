> **Historical document.** This is our original plan from Oct 3. The strategy and rules evolved:
> see [README.md](README.md) for the live design and [DECISIONS.md](DECISIONS.md) for every change.

# Roostoo APAC Quant Hackathon — Master Plan (Team150-negExp)

_Written 2026-10-03. Live trading: Oct 4 → Oct 17. Repo deadline: before Oct 14._

---

## 0. What actually decides whether we win

The judging is a funnel, and each stage needs something different from us:

| Stage | What is checked | What it means for us |
|---|---|---|
| **Screen 1: Compliance** (pass/fail) | Trade log matches the declared strategy. Commit history is traceable. No manual API calls. | Every trade comes from committed code. Never run ad-hoc scripts with the competition key. Never stop the bot or override it by hand. Trade on **every** day (at least 8–10 active days). |
| **Screen 2: Return** (top 20 per region) | (Final − Initial) / Initial | We need a clearly positive return. Many teams will lose money to fees and overtrading, so a steady +3–8% is likely enough. A huge return isn't required. |
| **Screen 3: Composite score** | 0.4·Sortino + 0.3·Sharpe + 0.3·Calmar | **70% of the weight punishes downside.** Calmar = return / max drawdown, so a small max drawdown is worth more than a big return. We need a smooth equity curve. |
| **Screen 4: Code review** | Clear logic, clean repo, runs continuously | A well-built, modular, tested and documented repo. This is where serious teams separate from the rest. |
| **Finale** | Presentation to Susquehanna and industry judges | A clear thesis, a rigorous backtest and an honest risk discussion. |

**Core thesis:** don't try to make the most money. Build the **smoothest positive equity curve** in the region, with low turnover, strict drawdown control and maker-fee execution, and back it with a strong engineering repo.

---

## 1. Hard facts from the API (verified 2026-10-03)

- Base URL: `https://mock-api.roostoo.com`. Signing is HMAC-SHA256 over sorted `k=v&k=v` params, sent in the `RST-API-KEY` and `MSG-SIGNATURE` headers. Every request needs a 13-digit `timestamp`.
- **Failures still return HTTP 200 with `Success:false`.** Always check `Success`.
- **Rate limit: 30 calls/min in total** (queries and orders together). We'll budget at most about 20/min.
- `GET /v3/ticker` **without `pair` returns all 88 pairs in one call**: bid, ask, last price, 24h change and 24h volume. One call per minute covers all live data.
- There is **no OHLCV** from Roostoo. Its prices are streamed from Binance, so we use **Binance klines** for history and indicators (`data-api.binance.vision`, free, no key).
- Spot orders: `/v3/place_order` with `MARKET` (taker, 0.1%) or `LIMIT` (maker, 0.05%). Orders must respect `AmountPrecision`, `PricePrecision` and `MiniOrder` from `/v3/exchangeInfo`.
- Shorts: `/v6/short_open` (sized by USD collateral), `/v6/short_close`, `/v6/short_positions`. **The fee is 0.1% for both market and limit**, and the response can be `"this competition does not allow short positions"`. **We must test whether shorting is enabled before relying on it.**
- Universe: 88 pairs. These include major coins (BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX, LINK, SUI…), meme coins (PEPE, BONK, WIF…), **PAXG (tokenized gold)** and tokenized stocks with a `…B` suffix (NVDAB, TSLAB…).
- Fee math: a round trip costs **0.2% taker/taker** or **0.1% maker/maker**. One hundred taker round trips at full size would cost about 20% of the portfolio. **Turnover is the enemy.**

---

## 2. Strategy design

### 2.1 Philosophy
- **Directional only:** no market-making and no arbitrage, as the rules require.
- **Medium frequency:** decide on 1h bars and rebalance at most once an hour, with deadbands. That works out to roughly 5–30 trades a day: enough to count as active every day, not enough for fees to eat the return.
- **Few parameters, robust and explainable.** Judges score "coherent logic", and finale judges will try to find overfitting.

### 2.2 The model: regime-gated, volatility-targeted trend portfolio

**Layer A — Universe filter (daily)**
- Keep crypto pairs that also exist on Binance spot, rank them by 24h USD volume, and take the top ~15.
- Exclude tokenized stocks (no Binance history to backtest on, and odd price behavior when markets are closed) and new or illiquid meme coins.

**Layer B — Market regime (hourly), based on BTC as the market factor**
- `RISK_ON`: BTC is above its EMA(~72h), the slope is positive and realized volatility isn't spiking.
- `NEUTRAL`: mixed signals. Hold a reduced gross exposure.
- `RISK_OFF`: BTC trend is down or volatility is spiking. Mostly cash, plus an optional small short sleeve if shorting is enabled.

**Layer C — Asset signals (hourly)**
- A time-series momentum score per asset, averaged over several lookbacks (e.g. 12h, 24h, 72h, 7d) and normalized by each asset's volatility.
- Rank the assets cross-sectionally and hold only the top N (≈3–6) that have a positive score.
- Optional confirmation: skip entries when the asset is far above its short-term mean (don't chase spikes).

**Layer D — Sizing (the part that drives Sharpe and Sortino)**
- **Inverse-volatility weights** and a **portfolio volatility target**. Gross exposure is scaled so that expected portfolio daily volatility stays at about 1–1.5%.
- Caps: no more than 30–35% in one asset, gross exposure of at most 100% (no leverage), and a cash buffer of at least 5%.

**Layer E — Risk overlay (the part that drives Calmar). It is automated because manual stops are banned.**
- Per-position stop of about 2.5×ATR(1h), plus a trailing stop once in profit.
- **Drawdown brake** on the whole portfolio: at −2% from peak equity, exposure is halved. At −4%, the bot goes to minimum exposure for a cooldown of N hours, then re-enters gradually.
- A daily loss limit and a check that blocks entries on stale data.

**Layer F — Short sleeve (optional, only if the API allows it)**
- In `RISK_OFF`, short the 1–3 weakest liquid coins with a small collateral budget (≤20–30% of equity).
- Shorts pay 0.1% each way, so the bar for opening one is higher.

**Why this should work:** trend-following with volatility targeting is one of the most robust documented effects in crypto. The regime gate keeps us out of the market during selloffs, which protects drawdown. Cash is a valid position (zero volatility), and it lifts Sortino and Calmar.

### 2.3 Fee-aware execution
- Use **maker-first** orders. Post a LIMIT at the best bid (or best ask when selling). If it hasn't filled after about 2–5 minutes, cancel and either re-post or fall back to MARKET. Stops and exits on the drawdown brake always go straight to MARKET.
- Use **deadbands**: only trade when the gap between target and current weight exceeds about 3–5% of equity, or 20% of the position. This cuts turnover a lot.
- Every trade must pass an **expected edge > cost** check: the edge has to beat about 2× the round-trip fee plus the spread.

### 2.4 Daily activity guarantee
The bot rebalances to its volatility targets at least once a day, so every day has trades driven by the strategy. Even in `RISK_OFF` it keeps a small allocation (e.g. a PAXG or BTC sleeve, or a short) so no day has zero activity. None of these trades are fake. They are all legitimate rebalancing.

### 2.5 Backup ideas (research only if time permits)
- Short-horizon mean reversion on BTC and ETH during low-volatility `NEUTRAL` regimes. This is only viable with maker fees.
- PAXG as a low-correlation defensive sleeve.
- A news or LLM sentiment filter. It's probably not worth the cost or risk for a two-week contest, but it's a good topic for the finale talk.

---

## 3. Research and backtesting

1. **Data:** Binance 1h klines (plus 15m for execution simulation) for the top ~25 coins, Jan 2024 → now. Cache them as parquet.
2. **Backtester:** an event-driven engine that uses **the exact same strategy code as the live bot** (one shared `strategy.compute_targets(state)` function). It models fees (0.1% taker / 0.05% maker), half-spread slippage, precision rounding, the minimum order size and the hourly decision delay.
3. **Metrics:** return, Sharpe, Sortino, Calmar, max drawdown, turnover, fees paid, trades per day, plus **our estimate of the judges' composite**, computed on daily and on hourly equity.
4. **Overfitting protection:**
   - Walk-forward validation: train on rolling windows, test on the next out-of-sample period.
   - Parameter-robustness heatmaps. We want a **plateau, not a peak**.
   - Test on **14-day windows** that match the contest, across many market regimes, and report the distribution of the composite score.
5. **Baselines:** buy-and-hold BTC, equal-weight buy-and-hold, and the strategy without its risk overlay. These show the value of each layer, which makes a great README and finale slide.

---

## 4. Engineering architecture

```
QTwork/
├── bot/
│   ├── api/          roostoo_client.py  (signing, rate limiter, retries, Success-check)
│   ├── data/         market_data.py     (Roostoo ticker poller + Binance klines + bar builder)
│   ├── strategy/     regime.py, signals.py, sizing.py, strategy.py (pure functions)
│   ├── risk/         risk_manager.py    (stops, DD brake, caps, sanity checks)
│   ├── execution/    executor.py        (targets→orders, maker-first, cancel/replace, precision)
│   ├── portfolio/    state.py           (reconcile balance + shorts + open orders each loop)
│   ├── storage/      db.py              (SQLite: orders, fills, equity, signals, api_calls)
│   ├── config/       settings.py + config.yaml
│   └── main.py       scheduler loop, heartbeat, graceful restart
├── backtest/         engine.py, data_download.py, metrics.py, reports/
├── research/         notebooks (parameter studies, plots)
├── scripts/          healthcheck.py, daily_report.py (read-only), deploy.sh
├── tests/            unit tests: signing, rounding, sizing, risk rules, executor (mocked API)
├── deploy/           roostoo-bot.service (systemd)
├── .env.example      (NO real keys), .gitignore (includes .env, data/, logs/)
├── requirements.txt, Dockerfile (optional), README.md
```

**Key engineering rules**
- **Stateless restarts:** on every loop and at startup, rebuild positions from `/v3/balance`, `/v6/short_positions` and pending orders. Never trust local memory alone.
- **Rate-limit budget per loop:** 1 ticker call, 1 balance call, plus orders. A token bucket enforces at most 20 calls/min, and exponential backoff handles errors.
- **Every API call is logged** (endpoint, params minus secrets, latency, Success, ErrMsg). Every order is also logged with the **reason** for the signal. This is our Trade Log Integrity evidence for Screen 1.
- **Hourly equity snapshots** are stored, so we can compute the same metrics the judges will.
- **Mode switch:** `MODE=paper | test | live`. The competition key is loaded only in `live` mode, and a guard refuses to use it before the start date.
- **Safety in code:** max order notional, max orders per hour, a stale-price check and a price sanity check (no order more than X% away from the ticker).

**Deployment (AWS EC2 in Sydney, connected through Session Manager)**
- Launch from `Hackathon-Starter-Template`, install Python, clone the **public** repo and add `.env` on the server only.
- Run it as a `systemd` service with `Restart=always`, so it recovers from crashes and reboots without anyone touching it.
- **Update procedure (this is what keeps the commit history clean):** commit → push → on EC2, `git pull` a tagged commit → restart the service. Each restart lines up with a commit in the log. Restarting only to deploy new committed code is normal. We'll document it in the README so it isn't mistaken for manual intervention.
- Before going live, check that the EC2 instance can reach `data-api.binance.vision`, with Roostoo ticker data as the fallback.

---

## 5. Timeline (it's tight, so ship v1 first and improve with commits)

| When | Deliverable |
|---|---|
| **Oct 3 (today)** | Repo skeleton, API client and tests. **Smoke test with the TEST key:** ticker, balance, small limit order + cancel, small market order, short open/close test. Data pipeline. **v1 strategy** (BTC/ETH/SOL trend + regime + volatility targeting + drawdown brake). Paper-run locally. Set up EC2 and systemd. |
| **Oct 4** | **Go live with v1 on the competition key** (conservative sizing). Monitor logs and the leaderboard. |
| **Oct 4–7** | Build the full backtester, download data, run walk-forward research on the multi-asset momentum + regime model, and tune the deadbands and volatility target. |
| **Oct 7–8** | Deploy **v2** (multi-asset, maker-first execution, short sleeve if allowed) through a clean commit and tag. |
| **Oct 8–12** | Harden the bot (edge cases, restarts). Daily metric reports. Write the README: strategy, rationale, backtest results, engine, fee handling, risk. |
| **Oct 13** | **Submit the repo link** (deadline: before Oct 14). Tag `v1.0-submission`. Keep trading. |
| **Oct 14–17** | Keep running. Change only what's clearly justified, with each change committed. |
| **Oct 21 → 27** | If we're finalists: build the deck (thesis, architecture, backtest vs live, risk, lessons). |

---

## 6. Team split (adjust to team size)

- **Engineer A (infra/execution):** API client, executor, state reconciliation, EC2, systemd, logging.
- **Researcher B (alpha):** data download, backtester, signal and parameter research, walk-forward.
- **Engineer C (risk/reporting):** risk manager, metrics and daily report, tests, README and the deck.

---

## 7. Risks and open questions to resolve today

1. **The start date conflicts.** The FAQ says the competition starts Sep 30 with the first trade by Oct 1 8pm. The slides and Luma say live trading runs Oct 4–17. → **Ask in the WhatsApp group now.** If the FAQ is right, we need a minimal compliant bot running today.
2. **Is shorting enabled in our competition?** Test it with the test key.
3. **The active-days requirement** is "8" on Luma and "10" on the slides. We'll trade every day regardless.
4. **The repo must be public. Never commit API keys.** Use a `.env` that git ignores and run a pre-commit secret scan.
5. **AWS invite:** accept it within 7 days.
6. **Normalization of the composite score is unknown.** Either way, small max drawdown and smooth daily returns help us.
