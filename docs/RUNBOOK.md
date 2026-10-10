# Operations runbook (Oct 10–17)

All commands run in the EC2 browser terminal: **AWS console → EC2 → Instances → tick the
instance → Connect → Session Manager → Connect.** Paste one block at a time.

> **Never** stop the bot by hand, place trades, or run anything with the competition key.
> The only allowed actions are: deploy committed code, read logs and reports.

---

### Daily check (read-only, about 1 minute)
```bash
cd /opt/roostoo-bot && sudo -u ec2-user .venv/bin/python -m scripts.daily_report
```
Healthy: equity close to the previous day's, `gross` around 55–70% (15–20% while the lock-in is active), recent orders with
status FILLED / OPEN / CLOSED, no loop errors. Today's rebalance runs at **00:01 UTC (05:31 IST)**.

### Is the bot running?
```bash
sudo systemctl status roostoo-bot --no-pager | head -5; sudo journalctl -u roostoo-bot -n 20 --no-pager
```
Healthy: `active (running)` and log lines from the last few minutes. systemd restarts the bot
automatically after a crash or reboot, so no manual restart is needed.

### Deploy the latest committed version
```bash
sudo bash /opt/roostoo-bot/deploy/deploy.sh && sleep 20 && sudo journalctl -u roostoo-bot -n 5 --no-pager
```
Healthy: `deployed <commit> (...)` and `starting bot in LIVE mode`. On restart the bot cancels
any half-finished orders and continues from the exchange's real positions.

### Roll back to a previous version (if a new version misbehaves)
```bash
sudo bash /opt/roostoo-bot/deploy/deploy.sh <commit-id>
```
For example `sudo bash /opt/roostoo-bot/deploy/deploy.sh 727857e`. Commit ids are on GitHub
or in DECISIONS.md. Run `sudo bash /opt/roostoo-bot/deploy/deploy.sh main` to return to the latest.

### Change the risk level (Plan A / Plan B)
Decided from the leaderboard with `python -m scripts.leaderboard_decision --ours X --rank20 Y --days-left D`
(see also `research/risk_table.py`, `research/plan_b.py`). The change
is made **in code and committed** (that keeps the commit history traceable), then deployed
with the command above.

| Situation | Setting (bot/config.py) |
|---|---|
| Top-20 cutoff ≤ 0% | default: `target_daily_vol = 0.012`, equal sleeve weights |
| Cutoff around 1–3% | `target_daily_vol = 0.016` |
| Cutoff 3–8% (Plan B) | `target_daily_vol = 0.016`, `sleeve_weights = (0.0, 0.5, 0.0, 0.5)` |

### Repo submission (before Oct 14)
Submit `https://github.com/wildwolf07/Roostoo-QT` as instructed in the WhatsApp group. The
final version is tagged `v1.0-submission`.

### What is normal
- Small daily P&L swings (backtest median 14-day max drawdown ~2.3%; p95 ~5%).
- 3–15 orders at each daily rebalance; few or none in between.
- Limit orders that are CANCELED and then filled at market: that is the maker-first execution.
- **Endgame lock-in (from Oct 10):** the bigger our gain, the smaller the book. At +1% or more
  the bot runs about a quarter of its normal size (`gross` around 15–20%). Below +1% it scales back
  up, and at 0% or a loss it runs full size. Right after the deploy that turns this on, expect one
  large round of SELL / short-close orders: that is the book shrinking, not a problem.
- From Oct 16 12:00 UTC exposure is halved again (end-of-contest taper, on top of the lock-in).
