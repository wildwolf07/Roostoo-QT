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
2. [x] Robustness of the ensemble: sensitivity grid (n per side 3/4/5, lookbacks, vol target,
       filter thresholds, universe 12/15/20); check plateau, not peak. Deflated-Sharpe style note.
3. [x] Execution alpha with zero turnover cost: use 1–4h reversal / BTC catch-up to TIME the
       daily rebalance (e.g. delay buys of coins that just pumped). Estimate bps saved per trade.
4. [x] Sleeve weights: equal vs inverse-vol vs recent-performance; and a 5th sleeve candidate
       (e.g. low-risk L/S restricted to calm shorts). Only adopt with IS+OOS evidence.
5. [x] Tail-risk study: behaviour in crash hours (e.g. 2025-10-10) and pump events; check
       short-squeeze exposure; stop calibration.
6. [x] Scoring-aware analysis: how vol target trades off P(top-20 return) against
       Sortino/Sharpe/Calmar over a 7-day horizon (Monte Carlo from backtest returns).
7. [x] Live monitoring script: composite score from equity log, live vs backtest tracking.
8. [x] Finale prep: decision log, deck outline (Oct 27 if finalist), README polish.

9. [x] Stress test on 2021-2022 (LUNA, FTX crashes, full bear market) as extra out-of-sample.
10. [ ] Finale deck outline + README final polish; tag v1.0-submission before Oct 14.

## Log
- 04:20 IST #1 DONE. research/overlay_study.py replays the live overlay on ensemble returns,
  14-day windows stepped 3.5 days. Current overlay (CPPI 0.96/m15, brake 1.5-4.5%, 24h limit)
  OOS median composite -0.78 vs none +2.67 vs loose brake (2.5-7%, no CPPI/24h) +2.70; IS the
  same ranking. Whipsaw: de-risks after small dips, misses rebounds. Adopted the loose brake;
  stops widened to 6-15% (disaster-only, untested; stops are not in the simulator).
  Commit 80a8062, pushed; user to deploy with deploy.sh.
- 04:40 IST #2 DONE (research/robustness.py). One-at-a-time grid around the live config:
  full-period Sharpe min 0.41 / median 0.68 / max 1.05; live config ranks 5/15, so it sits on a
  plateau rather than a tuned peak. Outlier upside: universe 20 (Sharpe 1.05, +65%, all years
  positive, IS and OOS composite both better). Breadth is monotonic (12: 0.58, 15: 0.73,
  20: 1.05), consistent with Grinold's fundamental law (IR ~ IC x sqrt(breadth)).
  Confirmation grid (universe x n) running: research/breadth_check.py.
- 04:45 IST #3 DONE (rejected). Execution timing: conditional forward relative returns for
  top vs bottom quintile of 4h reversal / BTC catch-up are only 1-2 bp at 1-4h, IS and OOS.
  Saving < 0.1% over the contest; not worth the complexity before the freeze.
- 05:00 IST breadth grid (research/breadth_check.py): Sharpe rises monotonically with universe
  size and is flat across n=3/4/5: uni15 0.65-0.76, uni20 0.94-1.05, uni25 1.15-1.26,
  uni31 1.35-1.40; all years positive; IS and OOS composites improve together. Caveat:
  survivorship (coin list = coins live on Roostoo today), strongest for the smallest coins.
  Roostoo spreads: < 5bp except PEPE 25bp, SHIB 18bp (tick size). Re-running without PEPE/SHIB.
- 05:00 IST #6 DONE (research/score_mc.py): 976 eight-day OOS stretches + 6 flat days.
  Median composite ~1.58 for exposure 0.75x-1.6x (scale-invariant); P(ret>2%) 12.7% -> 19.4%
  -> 24.4% -> 25.0% and P(ret<-3%) 1.7% -> 3.0% -> 7.5% -> 9.7%. Raising exposure only pays if
  we are below the top-20 cutoff: needs leaderboard numbers from the user. Default stays 1.0x.
- breadth without PEPE/SHIB confirmed (uni25 n4: Sharpe 1.27, +84%, OOS comp 4.02, all years > 1.0).
  ADOPTED live: whitelist 29 (no PEPE/SHIB), universe_size 25. Parity OK, tests OK, dry run OK.
- #4 DONE (research/ablation.py, universe 25). All 4: Sharpe 1.27, IS 1.84, OOS 4.02, MDD 16.9%.
  Without mom_f: Sharpe 1.30, IS 3.43 but OOS 3.35, MDD 19.8%. +5th sleeve (low-risk L/S, shorts
  only falling coins): MDD 14.6%, OOS 4.63 but IS 1.69, 2026 Sharpe 0.88 (the sleeve alone was -1.29
  in 2026). No alternative wins in BOTH periods, so NO CHANGE (rule). Sleeve correlations:
  mom_ls vs lowrisk_lo -0.19; mom_lo vs lowrisk_lo 0.79 (both long beta); mom_ls vs mom_f 0.74.
- #5 DONE (research/tail_study.py). Ensemble worst hour since 2023 -1.76% (market -11.7% that hour);
  2025-10-10/11 crash window: ensemble -2.32% vs market -20.6%, BTC -9.4%. Worst day -3.0%.
  Net exposure +0.31 on average (5-95%: +0.12..+0.49), gross 0.64, daily corr to market 0.68.
  Trailing stops HURT in both periods: none SR 1.27 (IS 0.84 / OOS 1.98, MDD 16.9%) vs live 6-15%
  stops SR 0.75 (0.35 / 1.46, MDD 18.2%); old 3-8% 0.74; wide 10-25% 0.94. DISABLED stops
  (commit 0412056, pushed, fresh clone OK). User deployed 640a349 and was given the command for 0412056.
- #7 DONE earlier: scripts/daily_report.py (contest-window composite estimate).
- #9 stress test (research/stress_test.py, 2021-01 -> 2022-12, never used for design; 21 coins).
  Calendar Sharpe 2021 2.81, 2022 -1.42 (then 2023 1.47, 2024 1.26, 2025 1.39, 2026 0.94).
  2021-02..2022-12: +19.8%, Sharpe 0.70, max DD 28.3% (BTC -49.2%). 98 fourteen-day windows:
  median +0.57%, P(>0) 56%, median MDD 2.94%, p95 6.32%, median composite 2.73.
  Crashes: LUNA -6.7% (market -23.2%), 3AC -4.2% (-21.2%), FTX -1.5% (-18.8%).
  Weakness = prolonged bear (net long +0.31 from the long-only sleeves). Testing a slow
  market-trend filter on the long-only sleeves (research/bear_filter.py).
- bear filter (research/bear_filter.py): turning long-only sleeves off when BTC < 50-day SMA:
  full Sharpe 1.08 -> 1.55, max DD 28.3% -> 19.0%, 5 of 6 years better (2024 worse), BUT median
  14-day composite 3.27 -> 1.95 (lags; misses rebounds in typical windows). Mixed evidence on the
  contest metric => NOT adopted. Contingency only: BTC is +2.3% above its SMA50 now (filter inactive).
- #8 DONE: docs/FINALE_DECK.md (10-slide storyline), DECISIONS.md, README "Results at a glance"
  with SVG charts (research/make_charts.py; no new dependencies). Shadow bot running on the TEST
  account on this Mac to mirror the live 00:00 UTC rebalance (logs/bot.log).
- robustness re-run at universe 25: Sharpe min 0.89 / median 1.22 / max 1.44; live rank 5/15 (plateau).
  n=3 and momentum-heavy weights look slightly better (Sharpe 1.29 / 1.32 vs 1.27), within noise
  after ~50 trials (deflated-Sharpe logic). NO CHANGE.
- next: end-of-contest taper test (score_mc variant).
- taper (score_mc): OOS median composite no-taper 1.80 vs taper 1.66 (P(ret>2%) 20.2% vs 17.5%);
  IS the opposite (0.47 vs 0.69). Mixed => NO CHANGE (taper stays).
- next: residual momentum (Blitz-Huij-Martens 2011) in the momentum sleeves.
- residual momentum (Blitz-Huij-Martens): 2023-26 Sharpe 1.27 -> 1.53, IS comp 1.84 -> 2.49, OOS
  4.02 -> 4.74, BUT on unseen 2021-22: +18.0% / SR 0.65 vs +19.8% / 0.70 and median 14d composite
  1.59 vs 2.73. Fails the unseen-data check => NOT adopted. Note: yearly Sharpe SE ~ +/-1, so
  "every year better" in the design period was weak evidence.
- next: deflated Sharpe ratio for the live ensemble given all trials run.
- DSR (live 25-coin ensemble): PSR 0.992; DSR 0.711 (N=42), 0.637 (N=80), 0.565 (N=150).
  Found and fixed: ensemble_returns() used universe 15; overlay/score_mc re-running at universe 25.
- overlay @ u25: catastrophe brake 6-12% adopted (commit 39a452d). Taper unchanged (mixed).
- deadband (research/deadband_study.py): 0% Sharpe 1.27 (IS 0.84 / OOS 1.97), comp 1.84/4.02;
  2% (live) 1.21 (0.91 / 1.72), comp 4.64/3.00; tracking error 13% of equity at 2%. Mixed
  (IS better, OOS worse) => NO CHANGE.
- CI added (GitHub Actions, py3.9 + 3.12): first run green (7aba1d1). README: badge, PSR/DSR, risk row.
- Robustness fixes (8b55426): Binance kline fallback hosts; cancel stale pending orders on startup.
  Shadow bot restarted on 8b55426 to mirror the 00:00 UTC (05:30 IST) live rebalance.
- MORNING DEPLOY NEEDED: live runs 727857e; latest = catastrophe brake + robustness fixes.
- vol-managed scaling (Moreira-Muir / Barroso-Santa-Clara): rejected (Sharpe 1.08 -> 0.73-1.00, worse 2022).
- single-name/short-squeeze risk: worst coin-day -2.1% of equity (short XLM 2023-07-13).
- recent regime (live config backtest): 14d -1.71% (DD 3.2%), 30d +1.08%, 60d +8.18% (SR 3.2),
  180d +13.47% (SR 1.9). Ordinary drawdown, not a regime break; set expectations accordingly.

## Morning session (Oct 10, 09:00-10:00 IST)
- Scheduler hardening (b1673d0): failed daily rebalance retried each minute up to 5x; tick() + tests.
- Leaderboard decision table + Plan B config switch (sleeve_weights) + scripts/leaderboard_decision.py.
- docs/JUDGES_QA.md, docs/RUNBOOK.md, README restructured to the organisers' checklist.
- Fee sensitivity: edge survives 2x taker fee (Sharpe 0.75 at 0.2%); break-even ~0.35%.
- Alpha decay: OOS per-day alpha front-loaded (7-9 bps/day for 3 days), supports ~3-day hold.
- Capacity: negligible impact at $100k; ~$5-10M limit without liquidity-weighted sizing.
- Survivorship: 72-coin point-in-time universe incl. delisted coins -> Sharpe 1.55 vs 1.08. No inflation.
- Bootstrap CI: Sharpe 1.28 [0.19, 2.34]; P(SR<=0) 1.1%.
- Whitelist expansion (+14 Roostoo coins): better OOS, worse 2021-22 and full Sharpe -> not adopted.
- Stopping point: further variants would raise the trial count (deflated-Sharpe penalty) without
  robust evidence; remaining value is in live monitoring and the leaderboard-driven risk decision.

## Live status
- Oct 10 08:32 UTC leaderboard: Team150-negExp #8/190 overall, #3 India, +1.0% (equity $101,003.85,
  drawdown 0.11%, fees 0.098%). India #1 Team107 (IITM) +1.6%, #2 Team109 (IIT Mandi) +1.3%.
  Only 8 teams above +1%. Decision: Plan A unchanged (P(clear #20) 77.5% vs 73.4% A+ vs 66.4% B).

## Evening session (Oct 10, 17:00-19:00 UTC): endgame lock-in
- Funnel re-read: compliance -> top 20 per region by RETURN -> composite (0.4 Sortino + 0.3 Sharpe +
  0.3 Calmar) -> code review -> top 5 per region = 15 finalists. Return is only the gate; the
  composite among the top 20 decides.
- Insight: ratio scores are scale-free only while nothing is banked. With gain B banked, future risk
  k grows the denominators (sd, downside dev, MDD ~ k) faster than the numerators (B + k*mu), so the
  window score rises as k falls. Tournament theory agrees: leaders cut risk, laggards add it.
- Crypto EW market Oct 4-9: -7.1% (Oct 8 -6.2%), which explains the weak field (only 8/190 > +1%).
- research/endgame.py: 5,350 historical 7.3-day stretches of the live ensemble, our realised path
  (flat to Oct 9 22:00, +1% banked), four readings of the formula (daily/hourly/active-days/raw).
  +1% banked: A (1x) median composite 10.6, P(R<0) 22%; L4 (1x -> 0.25x linearly as banked 0 -> +1%)
  median composite 30.0, p25 14.0, P(R<0) 8%, median R +1.15% vs +1.20%. Every lower-risk policy
  dominates A at every quantile; A+ (1.33x) is worse. The state-dependent L4 beats fixed 0.25x on
  return and when banked is 0 or +0.5% (it keeps risk when nothing is banked).
- Funnel model (3 hypothetical India fields, calibrated competitor vol/beta): P(top 20) A 79-89%,
  L4 83-87%; P(top 20 and top-5 composite) A 33-41% -> L4 62-67%.
- ADOPTED: RiskConfig.lockin_* (start Oct 10 12:00 UTC, full at +1%, min 0.25x) and the rebalance
  deadband scaled by exposure (min 0.25) so the smaller book tracks. Tests 27/27.
- Moonshot (research/moonshot.py): all-in bets reach the overall #1 return (+37%) in <=5.7% of
  stretches but halve P(finalist) (62-68% -> 26-30%) and do not raise P(#1 composite in India).
  Rejected. Note: a restart does not rebalance (last_rebalance_hour persists), so the lock-in
  deployed at 17:48 UTC takes effect at the Oct 11 00:01 UTC rebalance.

## Oct 11 (00:30-03:00 IST): real India field
- Rules re-read (organiser page): regions are separate (finalists AND prizes per region); 8 active
  days with trades each day (if counted in HKT our live days are exactly Oct 10-17 = 8, zero slack);
  no HFT / market making / arbitrage; spot 1x long/short, no leverage; judges pick the top 3 at the
  finale with their own criteria.
- India field (Oct 10 20:55 UTC): 107 +1.8, 109 +1.3, us +1.1, 145 +0.6, 180 +0.4, 139 0.0, then
  -0.4 ... India #20 at -5.2%. P(top 20) = 100% for every non-gambling plan.
- endgame.py (+ P(#1 comp), floors 0.15/0.10): P(top5 comp) 1x 62%, floor .25 90%, .15 93-94%,
  .10 95-96%; P(#1) 9% / 21-23% / 27-32% / 31-40%. Adopted floor 0.15 (keeps a tradeable book).
- Safety net 20:00 -> 12:00 UTC (same calendar day in UTC/HKT/IST). Deadband floor 0.25 -> 0.1.
- Moonshot on the real field: all-in volatile coin P(top5 comp) 39%, P(#1) 20% vs lock-in 90%/23%.

## Oct 11 morning check (05:50 UTC)
- 00:01 UTC rebalance: risk_mult 0.34 (gain had slipped to ~+0.78% overnight at full size, so the
  rule set 1 - 0.85*0.78). 24 orders, gross ~60% -> 22.9%, tracking error 1.1%. Now +0.65%,
  drawdown 0.46%, own composite estimate 42.4 (Sortino 34, Sharpe 5.7, Calmar 90). Fees 0.14% total.
- Re-run from this state (banked +0.65%, MDD 0.46%, India field of Oct 10): live rule (floor 0.15)
  P(top5 comp) 73%, P(#1) 18%, median R +0.96%; fixed 0.15x 75% / 18% / +0.65%; 1x 54% / 9%.
  The live rule is as good as a fixed small book and keeps more upside -> no change.
- Leaderboard refresh (Oct 11 ~05:55 UTC; it updates in snapshots): India 107 +1.6, 109 +1.1,
  145 +0.9, us +0.7 (#4), 179 0.0, 139 -0.5, 156 -0.6, 180 -0.8, 182 -0.8, ... Re-run on this
  field: live rule P(top 20) 100%, P(top5 comp) 74%, P(#1) 19% (1x: 54% / 10%). No change.
