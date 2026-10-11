# Research library

Every claim in the main README comes from a script in this folder. Each script answers one
question, prints its evidence, and can be re-run. Data comes from Binance's public API (the download
scripts) and is not committed. Generated results are committed in [`../results/`](../results/).

| Question | Script | Answer (details in [RESEARCH.md](../RESEARCH.md) and [DECISIONS.md](../DECISIONS.md)) |
|---|---|---|
| **Data** | `download_full.py`, `download_pre.py`, `download_broad.py` | Hourly spot, funding and premium 2023 → now; spot 2021–22 for the unseen stress test; a broad point-in-time universe including delisted coins |
| Which signals predict returns at our horizon? | `signal_lab.py` | 7–14 day momentum persists (positive rank IC at 1–3 days, in- and out-of-sample); 1–24h returns mean-revert (t ≈ −14); low-risk ranks predict well, but shorting them loses money (IC ≠ P&L) |
| How should the signals become a portfolio? | `xs_backtest.py` | Vectorised cross-sectional backtester (fees, tranching, beta-neutral legs, filters) used by every study below |
| What does each sleeve contribute? | `ablation.py` | Every single-sleeve removal hurts at least one period (in- or out-of-sample); only the full ensemble is good in both. Sleeve correlations are low or negative |
| Does breadth help? | `breadth_check.py` | Sharpe 0.89 → 1.14 → 1.27 for 15/20/25 coins; 3/4/5 coins per side within noise |
| Is the configuration a plateau or a peak? | `robustness.py` | Plateau: the live configuration ranks 5th of 15 one-at-a-time variants |
| Should we trade more coins? | `whitelist_expansion.py` | No: 14 extra Roostoo coins help recent data but hurt 2021–22 and the full-period Sharpe |
| Do risk overlays help the contest score? | `overlay_study.py` | Tight brakes, CPPI and 24h limits whipsaw; a catastrophe-only 6–12% brake is free insurance |
| Do per-coin stops help? Where are the tails? | `tail_study.py` | Stops cut Sharpe 1.27 → 0.75 without lowering max drawdown; worst coin-day −2.1% of equity |
| Volatility-managed scaling? | `vol_managed.py` | Rejected: full Sharpe 1.08 → 0.73–1.00 |
| A bear-market filter? | `bear_filter.py` | Fixes 2022 (full Sharpe 1.08 → 1.55) but lowers the median 14-day score; kept as a contingency |
| What does the deadband cost? | `deadband_study.py` | 2% deadband: Sharpe 1.27 → 1.21 and much lower fees; tracking error ~13% of equity |
| What volatility target maximises the contest score? | `score_mc.py`, `risk_table.py`, `plan_b.py` | 1.2% a day; more risk mainly fattens the loss tail |
| Does it survive data it never saw? | `stress_test.py` | 2021–22: +19.8% while BTC fell 54%; LUNA −6.5%, 3AC −4.1%, FTX −1.5% |
| Is it survivorship bias? | `survivorship.py` | No: on a 72-coin point-in-time universe with delisted coins, Sharpe 1.55 vs 1.08 |
| How likely is the edge real? | `deflated_sharpe.py`, `bootstrap_ci.py` | PSR 99%; deflated Sharpe 64–71% across all trials; bootstrap Sharpe 1.28 [0.19, 2.34] |
| Does the live bot trade what we tested? | `parity_check.py` | Yes: max weight difference 8e-17 at random historical dates |
| How much risk once a gain is banked? | `endgame.py`, `optimal_k.py`, `moonshot.py` | Closed-form k* = (μ/s²)(Q/S) and simulation: cut to ~0.05–0.1× once ahead; all-in bets halve P(finalist) ([docs/ENDGAME.md](../docs/ENDGAME.md)) |
| **Outputs** | `make_results.py`, `make_charts.py` | `results/backtest/*` (tear sheet, equity, years, 14-day windows, crashes, sleeves) and `docs/img/*.svg` |

The research log in time order is [`AGENDA.md`](AGENDA.md).
