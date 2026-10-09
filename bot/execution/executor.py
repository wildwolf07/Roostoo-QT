"""Turns target weights into exchange orders.

Design choices
- State is always rebuilt from the exchange (balance + ticker): no local position memory.
- Sells before buys, so freed USD funds the buys.
- Maker-first: post LIMIT at the touch (bid for buys, ask for sells) to pay 0.05%
  instead of 0.1%; whatever is unfilled after a timeout is cancelled and
  re-planned from fresh state as a MARKET order. Urgent exits go straight to MARKET.
- Deadband: ignore target/current gaps smaller than a fraction of equity (turnover control).
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from bot.api.roostoo_client import RoostooClient, ok
from bot.config import Settings
from bot.data.market_data import parse_ticker
from bot.storage.db import Database

log = logging.getLogger(__name__)


@dataclass
class Portfolio:
    usd_free: float
    usd_total: float
    qty_total: dict = field(default_factory=dict)
    qty_free: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)   # coin -> USD value at bid

    @property
    def equity(self) -> float:
        return self.usd_total + sum(self.values.values())

    def weights(self) -> dict:
        eq = self.equity
        return {c: v / eq for c, v in self.values.items()} if eq > 0 else {}


@dataclass
class OrderPlan:
    coin: str
    side: str
    qty: float
    reason: str


def build_portfolio(balance_resp: dict, ticker: dict) -> Portfolio:
    wallet = balance_resp.get("SpotWallet") or balance_resp.get("Wallet") or {}
    usd = wallet.get("USD", {})
    pf = Portfolio(usd_free=float(usd.get("Free", 0)),
                   usd_total=float(usd.get("Free", 0)) + float(usd.get("Lock", 0)))
    for coin, bal in wallet.items():
        if coin == "USD":
            continue
        total = float(bal.get("Free", 0)) + float(bal.get("Lock", 0))
        if total <= 0:
            continue
        pf.qty_total[coin] = total
        pf.qty_free[coin] = float(bal.get("Free", 0))
        px = ticker.get(coin, {}).get("bid") or ticker.get(coin, {}).get("last") or 0.0
        pf.values[coin] = total * px
    return pf


def floor_to(x: float, decimals: int) -> float:
    q = 10 ** decimals
    return math.floor(x * q + 1e-9) / q


class Executor:
    def __init__(self, client: RoostooClient, db: Database, settings: Settings, pair_info: dict):
        self.client = client
        self.db = db
        self.s = settings
        self.cfg = settings.execution
        self.pair_info = pair_info  # coin -> exchangeInfo TradePairs entry

    # ------------------------------------------------------------- state I/O
    def snapshot(self) -> Optional[tuple]:
        t = self.client.ticker()
        b = self.client.balance()
        if not ok(t) or not ok(b):
            log.error("snapshot failed: ticker=%s balance=%s", ok(t), ok(b))
            return None
        ticker = parse_ticker(t)
        return build_portfolio(b, ticker), ticker

    # ------------------------------------------------------------- planning
    def qty_decimals(self, coin: str) -> int:
        return int(self.pair_info.get(coin, {}).get("AmountPrecision", 4))

    def price_decimals(self, coin: str) -> int:
        return int(self.pair_info.get(coin, {}).get("PricePrecision", 4))

    def plan(self, targets: dict, pf: Portfolio, ticker: dict, deadband_frac: float,
             min_order_usd: Optional[float] = None, reason: str = "rebalance") -> list:
        min_usd = self.cfg.min_order_usd if min_order_usd is None else min_order_usd
        eq = pf.equity
        plans = []
        for coin in sorted(set(targets) | set(pf.values)):
            px = ticker.get(coin)
            if not px or px["bid"] <= 0 or coin not in self.pair_info:
                continue
            if not self.pair_info[coin].get("CanTrade", True):
                continue
            tgt_w = targets.get(coin, 0.0)
            cur_usd = pf.values.get(coin, 0.0)
            diff = tgt_w * eq - cur_usd
            full_exit = tgt_w <= 0 and cur_usd >= min_usd
            if not full_exit and abs(diff) < max(deadband_frac * eq, min_usd):
                continue
            dec = self.qty_decimals(coin)
            if diff < 0:
                qty = pf.qty_free.get(coin, 0.0) if tgt_w <= 0 else min(pf.qty_free.get(coin, 0.0), -diff / px["bid"])
                qty = floor_to(min(qty, self.cfg.max_order_frac * eq / px["bid"]), dec)
                if qty * px["bid"] >= max(min_usd if not full_exit else 1.0, 1.0):
                    plans.append(OrderPlan(coin, "SELL", qty, f"{reason}: w {cur_usd / eq:.3f}->{tgt_w:.3f}"))
            else:
                usd = min(diff, self.cfg.max_order_frac * eq)
                qty = floor_to(usd / px["ask"], dec)
                if qty * px["ask"] >= min_usd:
                    plans.append(OrderPlan(coin, "BUY", qty, f"{reason}: w {cur_usd / eq:.3f}->{tgt_w:.3f}"))
        return plans

    # ------------------------------------------------------------ execution
    def _send(self, p: OrderPlan, order_type: str, ticker: dict) -> Optional[dict]:
        pair = f"{p.coin}/USD"
        px = ticker[p.coin]
        price = None
        if order_type == "LIMIT":
            raw = px["bid"] if p.side == "BUY" else px["ask"]
            price = round(raw, self.price_decimals(p.coin))
        ref = px["last"] or px["bid"]
        if price and ref and abs(price / ref - 1) > self.cfg.max_price_deviation:
            log.error("price sanity check failed for %s: %s vs %s", pair, price, ref)
            return None
        qty_str = f"{p.qty:.{self.qty_decimals(p.coin)}f}"
        if not self.s.can_trade:
            log.info("[PAPER] %s %s %s %s @ %s (%s)", order_type, p.side, qty_str, pair, price, p.reason)
            self.db.log_order(self.s.mode, pair, p.side, order_type, p.qty, price, p.reason, None)
            return {"Success": True, "Paper": True}
        resp = self.client.place_order(pair, p.side, qty_str, order_type,
                                       None if price is None else f"{price:.{self.price_decimals(p.coin)}f}")
        self.db.log_order(self.s.mode, pair, p.side, order_type, p.qty, price, p.reason, resp)
        if not ok(resp):
            log.error("order rejected %s %s %s: %s", p.side, qty_str, pair, (resp or {}).get("ErrMsg"))
        else:
            d = resp["OrderDetail"]
            log.info("order %s %s %s %s -> %s @ %s", order_type, p.side, qty_str, pair, d.get("Status"),
                     d.get("FilledAverPrice") or price)
        return resp

    def _wait_for_fills(self, order_ids: set) -> None:
        deadline = time.monotonic() + self.cfg.limit_timeout_sec
        while order_ids and time.monotonic() < deadline:
            time.sleep(20)
            resp = self.client.query_order(pending_only=True)
            if resp is None:
                continue
            pending = {str(o["OrderID"]) for o in resp.get("OrderMatched", []) if o.get("Status") == "PENDING"}
            order_ids &= pending
        for oid in order_ids:
            r = self.client.cancel_order(order_id=oid)
            self.db.log_decision("cancel_unfilled_limit", {"order_id": oid, "resp": r})

    def _execute_side(self, side: str, targets: dict, deadband: float, reason: str,
                      urgent: bool, min_order_usd: Optional[float]) -> int:
        snap = self.snapshot()
        if not snap:
            return 0
        pf, ticker = snap
        plans = [p for p in self.plan(targets, pf, ticker, deadband, min_order_usd, reason) if p.side == side]
        if side == "BUY":
            plans = self._fit_to_cash(plans, pf, ticker)
        if not plans:
            return 0
        sent = 0
        if urgent or not self.s.can_trade:
            for p in plans:
                sent += ok(self._send(p, "MARKET", ticker))
            return sent
        # maker first
        pending = set()
        for p in plans:
            resp = self._send(p, "LIMIT", ticker)
            if ok(resp):
                sent += 1
                if resp["OrderDetail"].get("Status") == "PENDING":
                    pending.add(str(resp["OrderDetail"]["OrderID"]))
        if pending:
            self._wait_for_fills(pending)
            # anything still missing gets re-planned from fresh state as MARKET
            snap = self.snapshot()
            if snap:
                pf, ticker = snap
                rest = [p for p in self.plan(targets, pf, ticker, deadband, min_order_usd, reason + " (market fallback)")
                        if p.side == side]
                if side == "BUY":
                    rest = self._fit_to_cash(rest, pf, ticker)
                for p in rest:
                    sent += ok(self._send(p, "MARKET", ticker))
        return sent

    def _fit_to_cash(self, plans: list, pf: Portfolio, ticker: dict) -> list:
        budget = pf.usd_free * (1 - 2 * self.cfg.taker_fee) - 1.0
        need = sum(p.qty * ticker[p.coin]["ask"] for p in plans)
        if need <= budget or need <= 0:
            return plans
        scale = max(0.0, budget / need)
        out = []
        for p in plans:
            qty = floor_to(p.qty * scale, self.qty_decimals(p.coin))
            if qty * ticker[p.coin]["ask"] >= self.cfg.min_order_usd:
                out.append(OrderPlan(p.coin, p.side, qty, p.reason + f" (scaled {scale:.2f} to cash)"))
        return out

    def rebalance(self, targets: dict, deadband: Optional[float] = None, reason: str = "rebalance",
                  urgent: bool = False, min_order_usd: Optional[float] = None) -> int:
        deadband = self.cfg.deadband_frac if deadband is None else deadband
        n = self._execute_side("SELL", targets, deadband, reason, urgent, min_order_usd)
        n += self._execute_side("BUY", targets, deadband, reason, urgent, min_order_usd)
        return n

    def exit_positions(self, coins: list, reason: str) -> int:
        """Immediate MARKET exit (stops / emergency de-risking)."""
        snap = self.snapshot()
        if not snap:
            return 0
        pf, ticker = snap
        targets = {c: w for c, w in pf.weights().items() if c not in coins}
        plans = [p for p in self.plan(targets, pf, ticker, 0.0, 1.0, reason) if p.side == "SELL" and p.coin in coins]
        return sum(ok(self._send(p, "MARKET", ticker)) for p in plans)
