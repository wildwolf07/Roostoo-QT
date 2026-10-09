"""Bot entry point: an autonomous loop, no manual input.

Every minute : ticker + balance -> equity snapshot, risk update, trailing stops
Every hour   : hourly bars -> regime + momentum -> target weights -> rebalance
Every day    : guarantee strategy-driven activity (tight-deadband rebalance)

Run:  python -m bot.main            (MODE from .env: paper | test | live)
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler

from bot.api.roostoo_client import RoostooClient, ok
from bot.config import Settings, load_settings
from bot.data.market_data import MarketData, select_universe
from bot.execution.executor import Executor
from bot.risk.risk_manager import RiskManager, RiskState, utcnow
from bot.storage.db import Database
from bot.strategy.signals import apply_risk, compute_base_weights, hourly_vol, market_regime

log = logging.getLogger("bot")
RUNNING = True


def setup_logging(settings: Settings) -> None:
    settings.runtime.log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = TimedRotatingFileHandler(settings.runtime.log_dir / "bot.log", when="midnight", backupCount=30, utc=True)
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = [fh, sh]


class Bot:
    def __init__(self, settings: Settings):
        self.s = settings
        self.db = Database(settings.runtime.db_path.with_name(f"bot_{settings.mode}.db"))
        self.client = RoostooClient(settings.api_key, settings.api_secret, settings.runtime.base_url,
                                    settings.runtime.max_calls_per_minute, on_call=self.db.log_api_call)
        self.data = MarketData(settings.runtime.binance_url, settings.strategy.bar_interval,
                               settings.strategy.history_bars)
        self.risk = RiskManager(settings.risk, RiskState.from_json(self.db.get_kv("risk_state")),
                                initial_equity=self.db.get_kv("initial_equity"))
        self.pair_info: dict = {}
        self.executor: Executor | None = None
        self.last_rebalance_hour = self.db.get_kv("last_rebalance_hour")
        self.last_fill_day = self.db.get_kv("last_fill_day")
        self.last_info_refresh = 0.0

    # ------------------------------------------------------------ helpers
    def refresh_exchange_info(self) -> None:
        info = self.client.exchange_info()
        if info and info.get("TradePairs"):
            self.pair_info = {p.split("/")[0]: v for p, v in info["TradePairs"].items() if p.endswith("/USD")}
            self.executor = Executor(self.client, self.db, self.s, self.pair_info)
            self.last_info_refresh = time.time()

    def persist(self) -> None:
        self.db.set_kv("risk_state", self.risk.state.to_json())
        self.db.set_kv("last_rebalance_hour", self.last_rebalance_hour)
        self.db.set_kv("last_fill_day", self.last_fill_day)

    # --------------------------------------------------------- main steps
    def minute_step(self, now: datetime):
        snap = self.executor.snapshot()
        if not snap:
            return None
        pf, ticker = snap
        eq = pf.equity
        if self.db.get_kv("initial_equity") is None and eq > 0:
            # first ever observation of this account: anchor for return and CPPI floor
            self.db.set_kv("initial_equity", eq)
            self.risk.initial_equity = eq
            log.info("recorded initial equity %.2f", eq)
        self.risk.update_equity(eq, now)
        dd = self.risk.drawdown(eq)
        signed = pf.signed_values()
        gross = sum(abs(v) for v in signed.values()) / eq if eq else 0.0
        self.db.log_equity(eq, pf.usd_total, gross, dd, {c: round(v, 2) for c, v in signed.items()})

        prices = {c: (t["ask"] if signed.get(c, 0) < 0 else t["bid"]) for c, t in ticker.items()}
        stops = self.risk.check_stops(signed, prices, now, self.s.execution.min_order_usd)
        if stops:
            log.warning("trailing stop hit: %s", stops)
            self.db.log_decision("stop", {"coins": stops, "highs": {c: self.risk.state.position_highs.get(c) for c in stops}})
            if self.executor.exit_positions(stops, "trailing stop"):
                self.last_fill_day = now.date().isoformat()
            for c in stops:
                self.risk.start_cooldown(c, now)
        return pf, ticker

    def hourly_step(self, now: datetime, pf, ticker, force_daily: bool = False) -> None:
        cfg = self.s.strategy
        universe = select_universe(ticker, cfg.whitelist, cfg.universe_size, must_include=("BTC", cfg.core_asset))
        closes = self.data.hourly_closes(universe)
        if closes.empty or "BTC" not in closes:
            log.error("no market history available; skipping rebalance (stops remain active)")
            self.db.log_decision("skip_rebalance", {"reason": "no market data"})
            return
        closes = closes.dropna(axis=1, thresh=len(closes) // 2)
        vol_d = hourly_vol(closes, cfg.vol_lookback) * (24 ** 0.5)
        self.risk.state.asset_daily_vol.update({c: float(v) for c, v in vol_d.dropna().items()})

        regime = market_regime(closes["BTC"], cfg)
        blocked = self.risk.blocked(now)
        held = frozenset(c for c, v in pf.values.items() if v >= self.s.execution.min_order_usd)
        base, diag = compute_base_weights(closes, cfg, regime, blocked, held)
        risk_mult, risk_diag = self.risk.exposure_multiplier(pf.equity, now, sum(abs(v) for v in base.values()))
        targets = apply_risk(base, risk_mult, cfg, blocked)
        diag.update(risk=risk_diag, universe=universe, targets={c: round(w, 4) for c, w in targets.items()},
                    equity=round(pf.equity, 2), current={c: round(w, 4) for c, w in pf.weights().items()})
        log.info("decision regime=%s risk_mult=%.2f targets=%s", regime.label, risk_mult, diag["targets"])
        self.db.log_decision("rebalance", diag)

        if force_daily:
            n = self.executor.rebalance(targets, deadband=0.0, reason="daily rebalance", min_order_usd=50.0)
        else:
            n = self.executor.rebalance(targets, reason=f"scheduled rebalance [{regime.label}]")
        if n:
            self.last_fill_day = now.date().isoformat()

    def run(self) -> None:
        log.info("starting bot in %s mode", self.s.mode.upper())
        self.client.sync_time()
        self.refresh_exchange_info()
        if not self.executor:
            raise RuntimeError("could not load exchange info")
        if self.s.can_trade:
            # a restart can interrupt a rebalance; resting LIMIT orders from before the restart
            # would fill on top of freshly planned orders, so cancel them first
            resp = self.client.cancel_order()
            cancelled = (resp or {}).get("CanceledList") or []
            if cancelled:
                log.warning("cancelled %d stale pending orders on startup: %s", len(cancelled), cancelled)
                self.db.log_decision("startup_cancel_pending", {"orders": cancelled})
        while RUNNING:
            started = time.time()
            now = utcnow()
            try:
                if time.time() - self.last_info_refresh > 6 * 3600:
                    self.client.sync_time()
                    self.refresh_exchange_info()
                if now > self.s.runtime.live_end and self.s.mode == "live":
                    log.info("competition window over; idling")
                else:
                    snap = self.minute_step(now)
                    if snap:
                        pf, ticker = snap
                        hour_key = now.strftime("%Y-%m-%dT%H")
                        today = now.date().isoformat()
                        if hour_key != self.last_rebalance_hour and now.minute >= 1:
                            force = now.hour >= 20 and self.last_fill_day != today
                            first_run = self.last_rebalance_hour is None
                            scheduled = int(now.timestamp() // 3600) % self.s.strategy.rebalance_hours == 0
                            if first_run or force or scheduled:
                                self.hourly_step(now, pf, ticker, force_daily=force)
                            self.last_rebalance_hour = hour_key
                self.persist()
            except Exception:
                log.exception("loop iteration failed; continuing")
                self.db.log_decision("error", {"where": "main loop"})
            elapsed = time.time() - started
            time.sleep(max(1.0, self.s.runtime.loop_seconds - elapsed))
        self.persist()
        log.info("bot stopped")


def _stop(signum, frame):
    global RUNNING
    RUNNING = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Roostoo trend/regime trading bot")
    parser.add_argument("--mode", choices=["paper", "test", "live"], help="overrides MODE in .env")
    parser.add_argument("--once", action="store_true", help="run a single decision cycle and exit")
    args = parser.parse_args()
    settings = load_settings(args.mode)
    setup_logging(settings)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    bot = Bot(settings)
    if args.once:
        bot.client.sync_time()
        bot.refresh_exchange_info()
        now = utcnow()
        snap = bot.minute_step(now)
        if snap:
            bot.hourly_step(now, *snap)
        bot.persist()
        return
    bot.run()


if __name__ == "__main__":
    main()
