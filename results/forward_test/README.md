# Live forward test

The bot has traded the Roostoo competition account autonomously since 2026-10-09 21:51 UTC. The
contest window is Oct 4 12:00 → Oct 18 12:00 UTC. `LIVE_RESULTS.md` is a read-only export of the
bot's own SQLite audit log (`python -m scripts.export_live` on the server): the contest-window
summary, one row per contest day (equity, return, exposure, orders, fills, fees) and execution
statistics (maker share, fees, API success rate). It is refreshed at each daily check.
