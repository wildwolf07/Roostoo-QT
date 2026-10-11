"""Unit tests for the pieces where a bug would cost money: signing, sizing,
order planning, risk scaling. Run: python -m pytest -q  (or python -m unittest)"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from bot.api.roostoo_client import sign
from bot.config import ExecutionConfig, RiskConfig, Settings, StrategyConfig
from bot.execution.executor import Executor, Portfolio, build_portfolio, floor_to
from bot.risk.risk_manager import RiskManager
from bot.strategy.signals import Regime, apply_risk, market_regime, momentum_scores, target_weights

NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


def trending_closes(n=400, coins=("BTC", "ETH", "SOL"), drift=(0.001, 0.0005, -0.001), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-09-01", periods=n, freq="h", tz="UTC")
    data = {c: 100 * np.exp(np.cumsum(d + 0.005 * rng.standard_normal(n))) for c, d in zip(coins, drift)}
    return pd.DataFrame(data, index=idx)


class TestSigning(unittest.TestCase):
    def test_matches_official_example(self):
        params = {"pair": "BNB/USD", "quantity": "2000", "side": "BUY",
                  "timestamp": "1580774512000", "type": "MARKET"}
        secret = "S1XP1e3UZj6A7H5fATj0jNhqPxxdSJYdInClVN65XAbvqqMKjVHjA7PZj4W12oep"  # public doc example, allowlist-secret
        self.assertEqual(sign(params, secret),
                         "20b7fd5550b67b3bf0c1684ed0f04885261db8fdabd38611e9e6af23c19b7fff")  # allowlist-secret


class TestSignals(unittest.TestCase):
    def test_momentum_ranks_uptrend_first(self):
        scores = momentum_scores(trending_closes(), StrategyConfig())
        self.assertEqual(scores.index[0], "BTC")
        self.assertLess(scores["SOL"], 0)

    def test_weights_respect_caps_and_skip_downtrends(self):
        cfg = StrategyConfig()
        w, _ = target_weights(trending_closes(), cfg, Regime("RISK_ON", 1.0))
        self.assertNotIn("SOL", w)
        self.assertTrue(all(x <= cfg.max_weight + 1e-9 for x in w.values()))
        self.assertLessEqual(sum(w.values()), cfg.max_gross + 1e-9)

    def test_risk_off_keeps_only_core(self):
        cfg = StrategyConfig()
        w, _ = target_weights(trending_closes(), cfg, Regime("RISK_OFF", 0.0))
        final = apply_risk(w, 1.0, cfg)
        self.assertEqual(set(final), {cfg.core_asset} if cfg.min_gross > 0 else set())

    def test_downtrend_is_risk_off(self):
        closes = trending_closes(drift=(-0.002, 0, 0))
        self.assertEqual(market_regime(closes["BTC"], StrategyConfig()).label, "RISK_OFF")


class TestRisk(unittest.TestCase):
    def test_drawdown_brake_reduces_exposure(self):
        rm = RiskManager(RiskConfig(dd_soft=0.015, dd_hard=0.045, lockin_full_at=0.0))
        rm.update_equity(105_000, NOW - timedelta(hours=30))
        full, _ = rm.exposure_multiplier(105_000, NOW, 0.5)
        hurt, _ = rm.exposure_multiplier(100_000, NOW, 0.5)   # ~4.8% drawdown
        self.assertEqual(full, 1.0)
        self.assertLessEqual(hurt, 0.25 + 1e-9)

    def test_endgame_lockin_scales_with_banked_return(self):
        cfg = RiskConfig(lockin_start=NOW, lockin_full_at=0.01, lockin_min_mult=0.25)
        rm = RiskManager(cfg, initial_equity=100_000)
        rm.update_equity(101_000, NOW)
        before, _ = rm.exposure_multiplier(101_000, NOW - timedelta(hours=1), 0.6)
        self.assertEqual(before, 1.0)                                   # not active yet
        for equity, expected in ((99_000, 1.0), (100_000, 1.0), (100_500, 0.625), (101_000, 0.25), (103_000, 0.25)):
            mult, d = rm.exposure_multiplier(equity, NOW, 0.6)
            self.assertAlmostEqual(mult, expected, places=9)
            self.assertAlmostEqual(d["lockin_mult"], expected, places=3)

    def test_endgame_lockin_combines_with_taper(self):
        cfg = RiskConfig(lockin_start=NOW, lockin_full_at=0.01, lockin_min_mult=0.25, taper_start=NOW, taper_mult=0.5)
        rm = RiskManager(cfg, initial_equity=100_000)
        rm.update_equity(102_000, NOW)
        mult, _ = rm.exposure_multiplier(102_000, NOW, 0.6)
        self.assertAlmostEqual(mult, 0.125)

    def test_cppi_limits_gross_near_floor(self):
        rm = RiskManager(RiskConfig(cppi_floor=0.96))
        rm.update_equity(97_000, NOW)
        mult, d = rm.exposure_multiplier(97_000, NOW, 0.9)
        self.assertLess(mult, 0.5)

    def test_trailing_stop_triggers(self):
        rm = RiskManager(RiskConfig(stops_enabled=True, stop_vol_mult=2.5, stop_min=0.03, stop_max=0.08))
        rm.state.asset_daily_vol["ETH"] = 0.02     # stop = max(3%, 2.5*2%) = 5%
        self.assertEqual(rm.check_stops({"ETH": 10_000}, {"ETH": 100.0}, NOW, 200), [])
        self.assertEqual(rm.check_stops({"ETH": 10_000}, {"ETH": 94.0}, NOW, 200), ["ETH"])


class TestExecutionPlanning(unittest.TestCase):
    def setUp(self):
        info = {"BTC": {"AmountPrecision": 5, "PricePrecision": 2, "CanTrade": True},
                "ETH": {"AmountPrecision": 4, "PricePrecision": 2, "CanTrade": True}}
        settings = Settings(mode="paper", api_key="k", api_secret="s")
        self.ex = Executor(client=None, db=None, settings=settings, pair_info=info)
        self.ticker = {"BTC": {"bid": 80_000.0, "ask": 80_000.01, "last": 80_000.0},
                       "ETH": {"bid": 4_000.0, "ask": 4_000.01, "last": 4_000.0}}

    def test_floor_to(self):
        self.assertEqual(floor_to(0.123456789, 5), 0.12345)

    def test_build_portfolio_reads_spot_wallet(self):
        resp = {"Success": True, "SpotWallet": {"USD": {"Free": 90_000, "Lock": 0},
                                                "BTC": {"Free": 0.125, "Lock": 0}}}
        pf = build_portfolio(resp, self.ticker)
        self.assertAlmostEqual(pf.equity, 100_000)

    def test_plan_buys_and_exits(self):
        pf = Portfolio(usd_free=50_000, usd_total=50_000, qty_total={"ETH": 12.5},
                       qty_free={"ETH": 12.5}, values={"ETH": 50_000})
        plans = self.ex.plan({"BTC": 0.3}, pf, self.ticker, deadband_frac=0.02)
        sides = {p.coin: p.side for p in plans}
        self.assertEqual(sides, {"BTC": "BUY", "ETH": "SELL"})
        eth = next(p for p in plans if p.coin == "ETH")
        self.assertLessEqual(eth.qty, 12.5)

    def test_deadband_suppresses_small_trades(self):
        pf = Portfolio(usd_free=70_000, usd_total=70_000, qty_total={"BTC": 0.375},
                       qty_free={"BTC": 0.375}, values={"BTC": 30_000})
        self.assertEqual(self.ex.plan({"BTC": 0.31}, pf, self.ticker, deadband_frac=0.02), [])


class TestShorts(unittest.TestCase):
    def setUp(self):
        info = {"BTC": {"AmountPrecision": 5, "PricePrecision": 2, "CanTrade": True},
                "SOL": {"AmountPrecision": 3, "PricePrecision": 2, "CanTrade": True}}
        self.ex = Executor(client=None, db=None, settings=Settings(mode="paper", api_key="k", api_secret="s"),
                           pair_info=info)
        self.ticker = {"BTC": {"bid": 80_000.0, "ask": 80_000.01, "last": 80_000.0},
                       "SOL": {"bid": 100.0, "ask": 100.01, "last": 100.0}}

    def test_portfolio_counts_short_position_value(self):
        bal = {"Success": True, "SpotWallet": {"USD": {"Free": 90_000, "Lock": 0}}}
        shorts = {"Success": True, "Positions": [{"Pair": "SOL/USD", "ShortQty": 100, "CurrentPrice": 95,
                                                   "Collateral": 10_000, "PositionValue": 10_500}]}
        pf = build_portfolio(bal, self.ticker, shorts)
        self.assertAlmostEqual(pf.equity, 100_500)
        self.assertAlmostEqual(pf.weights()["SOL"], -9_500 / 100_500)

    def test_short_collateral_not_double_counted(self):
        # real Roostoo response shape: USD Lock includes ShortCollateral
        bal = {"Success": True, "SpotWallet": {"USD": {"Free": 90_000, "Lock": 10_000, "ShortCollateral": 10_000}}}
        shorts = {"Success": True, "Positions": [{"Pair": "SOL/USD", "ShortQty": 100, "CurrentPrice": 100,
                                                   "Collateral": 10_000, "PositionValue": 10_000}]}
        self.assertAlmostEqual(build_portfolio(bal, self.ticker, shorts).equity, 100_000)

    def test_plan_opens_and_closes_shorts(self):
        pf = Portfolio(usd_free=100_000, usd_total=100_000)
        plans = self.ex.plan({"SOL": -0.2}, pf, self.ticker, 0.02)
        self.assertEqual([(p.coin, p.side, p.qty) for p in plans], [("SOL", "SHORT_OPEN", 20_000.0)])
        pf = Portfolio(usd_free=80_000, usd_total=80_000, short_notional={"SOL": 20_000}, short_value={"SOL": 20_000})
        plans = self.ex.plan({}, pf, self.ticker, 0.02)
        self.assertEqual([(p.side, p.qty) for p in plans], [("SHORT_CLOSE", 100.0)])

    def test_stops_disabled_by_default(self):
        rm = RiskManager(RiskConfig())
        self.assertEqual(rm.check_stops({"ETH": 10_000}, {"ETH": 100.0}, NOW, 200), [])
        self.assertEqual(rm.check_stops({"ETH": 10_000}, {"ETH": 50.0}, NOW, 200), [])

    def test_short_trailing_stop(self):
        rm = RiskManager(RiskConfig(stops_enabled=True, stop_vol_mult=2.5, stop_min=0.03, stop_max=0.08))
        rm.state.asset_daily_vol["SOL"] = 0.02          # 5% stop
        self.assertEqual(rm.check_stops({"SOL": -10_000}, {"SOL": 100.0}, NOW, 200), [])
        self.assertEqual(rm.check_stops({"SOL": -10_000}, {"SOL": 90.0}, NOW, 200), [])
        self.assertEqual(rm.check_stops({"SOL": -10_000}, {"SOL": 94.6}, NOW, 200), ["SOL"])

    def test_short_sleeve_only_in_risk_off(self):
        from dataclasses import replace
        cfg = replace(StrategyConfig(), enable_shorts=True)
        closes = trending_closes(drift=(-0.002, -0.001, -0.003))
        w_off, _ = target_weights(closes, cfg, Regime("RISK_OFF", 0.0))
        self.assertTrue(w_off and all(v < 0 for v in w_off.values()))
        w_on, _ = target_weights(closes, cfg, Regime("RISK_ON", 1.0))
        self.assertTrue(all(v >= 0 for v in w_on.values()))


class TestEnsemble(unittest.TestCase):
    def setUp(self):
        coins = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "LINK", "AVAX", "DOT", "LTC", "TRX"]
        drifts = np.linspace(0.002, -0.002, len(coins))
        self.closes = trending_closes(n=500, coins=coins, drift=tuple(drifts), seed=3)

    def test_ensemble_weights_are_bounded_and_mixed(self):
        from bot.strategy.signals import ensemble_weights
        cfg = StrategyConfig()
        w, diag = ensemble_weights(self.closes, cfg)
        self.assertTrue(w)
        self.assertTrue(all(np.isfinite(v) for v in w.values()))
        self.assertLessEqual(sum(abs(v) for v in w.values()), cfg.max_gross + 1e-9)
        self.assertTrue(any(v > 0 for v in w.values()) and any(v < 0 for v in w.values()))
        self.assertEqual(set(diag["sleeves"]), {"mom_ls", "mom_lo", "mom_filtered_ls", "lowrisk_lo"})
        # strongest uptrend is long in the momentum sleeves, strongest downtrend is shorted there;
        # sleeves may net against each other (e.g. low-risk sleeve buying a calm downtrend coin)
        self.assertGreater(diag["sleeves"]["mom_lo"].get("BTC", 0), 0)
        self.assertLess(diag["sleeves"]["mom_ls"].get("TRX", 0), 0)
        self.assertTrue(all(v > 0 for v in diag["sleeves"]["lowrisk_lo"].values()))

    def test_sleeve_weights_plan_b_is_long_only(self):
        from dataclasses import replace
        from bot.strategy.signals import ensemble_weights
        cfg = replace(StrategyConfig(), sleeve_weights=(0.0, 0.5, 0.0, 0.5))
        w, diag = ensemble_weights(self.closes, cfg)
        self.assertTrue(w and all(v > 0 for v in w.values()))
        equal, _ = ensemble_weights(self.closes, StrategyConfig())
        self.assertNotEqual(set(w), set(equal) | {"__never__"})

    def test_blocked_coins_are_excluded(self):
        from bot.strategy.signals import ensemble_weights
        w, _ = ensemble_weights(self.closes, StrategyConfig(), blocked=frozenset({"ETH"}))
        self.assertNotIn("ETH", w)


class TestSchedulerRetry(unittest.TestCase):
    """Bot.tick: a failed scheduled rebalance is retried each minute, at most MAX_REBALANCE_ATTEMPTS."""

    def make_bot(self, outcomes):
        import time as _time
        from bot import main as m

        bot = m.Bot.__new__(m.Bot)
        bot.s = Settings(mode="paper", api_key="k", api_secret="s")
        bot.last_info_refresh = _time.time()
        bot.last_rebalance_hour = "2026-10-09T23"
        bot.last_fill_day = "2026-10-10"
        bot.rebalance_attempts = {}
        bot.persist = lambda: None
        bot.minute_step = lambda now: ("pf", "ticker")
        calls = []

        def hourly_step(now, pf, ticker, force_daily=False):
            calls.append(now)
            out = outcomes[len(calls) - 1] if len(calls) <= len(outcomes) else True
            if isinstance(out, Exception):
                raise out
            return out
        bot.hourly_step = hourly_step

        class _DB:
            def log_decision(self, *a, **k):
                pass
        bot.db = _DB()
        return bot, calls

    def test_retries_until_success(self):
        bot, calls = self.make_bot([False, RuntimeError("binance down"), True])
        for minute in range(1, 6):
            bot.tick(datetime(2026, 10, 10, 0, minute, tzinfo=timezone.utc))
        self.assertEqual(len(calls), 3)
        self.assertEqual(bot.last_rebalance_hour, "2026-10-10T00")

    def test_stands_down_after_max_attempts(self):
        from bot.main import MAX_REBALANCE_ATTEMPTS
        bot, calls = self.make_bot([False] * 20)
        for minute in range(1, 20):
            bot.tick(datetime(2026, 10, 10, 0, minute, tzinfo=timezone.utc))
        self.assertEqual(len(calls), MAX_REBALANCE_ATTEMPTS)
        self.assertEqual(bot.last_rebalance_hour, "2026-10-10T00")

    def test_safety_net_trades_by_noon_utc(self):
        from bot.main import FORCE_HOUR_UTC
        bot, calls = self.make_bot([True] * 5)
        bot.last_rebalance_hour = "2026-10-11T00"
        bot.last_fill_day = "2026-10-10"                                  # nothing filled on Oct 11 yet
        bot.tick(datetime(2026, 10, 11, FORCE_HOUR_UTC - 1, 30, tzinfo=timezone.utc))
        self.assertEqual(calls, [])
        bot.tick(datetime(2026, 10, 11, FORCE_HOUR_UTC, 1, tzinfo=timezone.utc))
        self.assertEqual(len(calls), 1)
        self.assertLessEqual(FORCE_HOUR_UTC, 15)                          # before the HKT day ends (16:00 UTC)

    def test_only_scheduled_hour_rebalances(self):
        bot, calls = self.make_bot([True] * 5)
        bot.tick(datetime(2026, 10, 10, 5, 3, tzinfo=timezone.utc))      # not scheduled, fills today
        self.assertEqual(calls, [])
        bot.tick(datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc))      # minute 0: waits for closed bar
        self.assertEqual(calls, [])
        bot.tick(datetime(2026, 10, 11, 0, 1, tzinfo=timezone.utc))
        self.assertEqual(len(calls), 1)


class TestMarketDataCache(unittest.TestCase):
    def test_falls_back_to_cached_bars_when_all_hosts_fail(self):
        from unittest import mock
        from bot.data import market_data as md
        idx = pd.date_range(end=NOW - timedelta(hours=1), periods=5, freq="1h")
        good = pd.DataFrame({"close": [1.0, 2.0, 3.0, 4.0, 5.0], "close_time": idx + timedelta(minutes=59, seconds=59)}, index=idx)
        m = md.MarketData("https://example.invalid", history_bars=5)
        with mock.patch.object(md, "fetch_klines", return_value=good), mock.patch.object(md, "closed_bars_only", side_effect=lambda d: d):
            first = m.hourly_closes(["BTC"])
        with mock.patch.object(md, "fetch_klines", side_effect=RuntimeError("down")), mock.patch.object(md.time, "sleep"):
            second = m.hourly_closes(["BTC", "ETH"])
        self.assertEqual(list(second.columns), ["BTC"])                  # ETH never seen: still skipped
        self.assertTrue(second["BTC"].equals(first["BTC"]))


class TestHourlyStep(unittest.TestCase):
    def test_deadband_scales_with_exposure(self):
        from bot import main as m
        from bot.risk.risk_manager import RiskManager
        from bot.storage.db import Database
        import tempfile, pathlib

        bot = m.Bot.__new__(m.Bot)
        bot.s = Settings(mode="paper", api_key="k", api_secret="s")
        bot.db = Database(pathlib.Path(tempfile.mkdtemp()) / "t.db")
        coins = list(bot.s.strategy.whitelist)
        rng = np.random.default_rng(0)
        idx = pd.date_range(end=NOW, periods=600, freq="1h")
        closes = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, 0.01, (600, len(coins))), axis=0)) * 10, idx, coins)
        bot.data = type("D", (), {"hourly_closes": lambda self, u: closes[u]})()
        ticker = {c: {"last": 10.0, "bid": 10.0, "ask": 10.0, "volume_usd": 1e6 + i} for i, c in enumerate(coins)}
        pf = Portfolio(usd_free=101_000, usd_total=101_000, values={})
        seen = []
        bot.executor = type("E", (), {"rebalance": lambda self, t, deadband=None, min_order_usd=None, **k:
                                      seen.append((deadband, min_order_usd)) or 0})()
        # full book: normal 2% deadband; half book: scaled; locked-in small book: $50 threshold
        for equity, band, min_usd in ((100_000, 0.02, None), (100_100, 0.02 * 0.64, None), (101_000, 0.0005, 50.0)):
            bot.risk = RiskManager(RiskConfig(lockin_start=NOW, lockin_full_at=0.0025, lockin_min_mult=0.10),
                                   initial_equity=100_000)
            pf.usd_free = pf.usd_total = equity
            self.assertTrue(bot.hourly_step(NOW, pf, ticker))
            self.assertAlmostEqual(seen[-1][0], band)
            self.assertEqual(seen[-1][1], min_usd)


if __name__ == "__main__":
    unittest.main()
