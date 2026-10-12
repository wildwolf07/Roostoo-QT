# Operations runbook

All commands run on the EC2 host through AWS Systems Manager Session Manager (no SSH keys, no open
ports): **AWS console → EC2 → Instances → select the instance → Connect → Session Manager.**

> The bot is fully autonomous. Operators never place trades, stop the bot by hand, or use the
> competition API key. The only operator actions are reading logs and reports, and deploying
> committed code.

## Schedule (UTC)

| When | What |
|---|---|
| every 60 s | Snapshot balances and positions from the exchange; log equity; update risk state |
| 00:01 | Daily rebalance: signals → ensemble → risk layer → orders (maker-first, market fallback) |
| 10:00 | Safety net: if nothing has filled today, rebalance with no deadband (guarantees a trade every day) |
| Oct 16 12:00 onwards | End-of-contest taper ×0.5, applied from the next rebalance |
| Oct 18 12:00 | Contest ends (Oct 18 17:30 IST); the bot stops trading and idles |

## Daily check (read-only, about a minute)
```bash
cd /opt/roostoo-bot && sudo -u ec2-user .venv/bin/python -m scripts.daily_report
```
Healthy: equity close to the previous day's; recent orders FILLED, OPEN or CLOSED; no loop errors.
Gross exposure is about 55–70% at full size, and about 4–6% while the endgame lock-in is active.

Confirm the latest rebalance and its risk multiplier:
```bash
sudo journalctl -u roostoo-bot -n 300 --no-pager | grep -E "risk_mult|rebalance complete" | tail -2
```

## Is the bot running?
```bash
sudo systemctl status roostoo-bot --no-pager | head -5; sudo journalctl -u roostoo-bot -n 20 --no-pager
```
Healthy: `active (running)` and log lines from the last few minutes. systemd restarts the bot
automatically after a crash or a reboot.

## Export the live results (read-only)
```bash
cd /opt/roostoo-bot && sudo -u ec2-user .venv/bin/python -m scripts.export_live --curve
```
Prints the contest-window summary, one row per contest day, execution statistics and the hourly
equity curve. The output goes into `results/forward_test/`.

## Deploy a committed version
```bash
sudo bash /opt/roostoo-bot/deploy/deploy.sh && sleep 20 && sudo journalctl -u roostoo-bot -n 5 --no-pager
```
The script checks out the commit, installs requirements, runs the unit tests, and only then restarts
the service. Healthy: `deployed <commit> (...)` and `starting bot in LIVE mode`. A restart does not
trigger a rebalance. The bot cancels any half-finished orders, rebuilds its state from the exchange,
and applies new settings at the next scheduled rebalance.

Roll back: `sudo bash /opt/roostoo-bot/deploy/deploy.sh <commit-id>` (commit ids are in
[DECISIONS.md](../DECISIONS.md)); return to the latest with `... deploy.sh main`.

If the repository is private, the host needs read access to pull: add a read-only **deploy key**
(GitHub → Settings → Deploy keys) and point the host's remote at the SSH URL.

## What is normal
- Small daily P&L moves. Backtest median 14-day max drawdown is 2.4–2.9%; live so far 0.44%.
- Limit orders that are CANCELED after 3 minutes and then filled at market: maker-first execution.
- **Endgame lock-in:** the bigger the banked gain, the smaller the book. From +0.25% the bot runs
  at 7.5% of its normal size and trades every target change of $50 or more (about 10 small orders a
  day). It returns to full size only if the gain is gone.
- From the Oct 17 rebalance exposure is halved again (taper, on top of the lock-in).
