# Overnight research agenda (autonomous loop, started 2026-10-10 ~04:15 IST)

Ground rules
- Never use the competition (LIVE) API key. Test key only for exchange experiments.
- Never deploy to EC2 (needs the user). Push to GitHub only verified work
  (tests pass + fresh-clone check). Live code changes must keep `research.parity_check` OK.
- Every claim needs IS/OOS evidence with fees; log results here and in RESEARCH.md.
- Deadline context: repo submission before Oct 14; live trading ends Oct 17; freeze Oct 13.

## Queue (highest value first)
1. [x] Risk-overlay calibration: add the live overlay (DD brake, CPPI, 24h limit, trailing stop)
       to the vectorised backtester; measure its effect on 14-day composite, P(top-k return),
       max DD. Tune only if gains are robust IS and OOS.
2. [ ] Robustness of the ensemble: sensitivity grid (n per side 3/4/5, lookbacks, vol target,
       filter thresholds, universe 12/15/20); check plateau, not peak. Deflated-Sharpe style note.
3. [ ] Execution alpha with zero turnover cost: use 1–4h reversal / BTC catch-up to TIME the
       daily rebalance (e.g. delay buys of coins that just pumped). Estimate bps saved per trade.
4. [ ] Sleeve weights: equal vs inverse-vol vs recent-performance; and a 5th sleeve candidate
       (e.g. low-risk L/S restricted to calm shorts). Only adopt with IS+OOS evidence.
5. [ ] Tail-risk study: behaviour in crash hours (e.g. 2025-10-10) and pump events; check
       short-squeeze exposure; stop calibration.
6. [ ] Scoring-aware analysis: how vol target trades off P(top-20 return) against
       Sortino/Sharpe/Calmar over a 7-day horizon (Monte Carlo from backtest returns).
7. [ ] Live monitoring script: composite score from equity log, live vs backtest tracking.
8. [ ] Finale prep: decision log, deck outline (Oct 27 if finalist), README polish.

## Log
- 04:20 IST #1 DONE. research/overlay_study.py replays the live overlay on ensemble returns,
  14-day windows stepped 3.5 days. Current overlay (CPPI 0.96/m15, brake 1.5-4.5%, 24h limit)
  OOS median composite -0.78 vs none +2.67 vs loose brake (2.5-7%, no CPPI/24h) +2.70; IS the
  same ranking. Whipsaw: de-risks after small dips, misses rebounds. Adopted the loose brake;
  stops widened to 6-15% (disaster-only, untested; stops are not in the simulator).
  Commit 80a8062, pushed; user to deploy with deploy.sh.
