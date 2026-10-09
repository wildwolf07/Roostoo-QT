"""Turns signed target weights (long > 0, short < 0) into exchange orders.

Design choices
- State is always rebuilt from the exchange (balance + short positions + ticker):
  no local position memory, so restarts are safe.
- Risk-reducing orders first (SELL, SHORT_CLOSE), then risk-adding (BUY, SHORT_OPEN),
  so freed USD funds the new positions.
- Maker-first for spot: post LIMIT at the touch (bid for buys, ask for sells) to pay
  0.05% instead of 0.1%; whatever is unfilled after a timeout is cancelled and
  re-planned from fresh state as a MARKET order. Urgent exits go straight to MARKET.
- Shorts use /v6 endpoints at market (their fee is 0.1% for market and limit alike).
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

REDUCE = ("SELL", "SHORT_CLOSE")
ADD = ("BUY", "SHORT_OPEN")


@dataclass
class Portfolio:
    usd_free: float
    usd_total: float
    qty_total: dict = field(default_factory=dict)
    qty_free: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)          # coin -> long USD value at bid
    short_notional: dict = field(default_factory=dict)  # coin -> |short qty| * current price
    short_value: dict = field(default_factory=dict)     # coin -> collateral + unrealised PnL

    @property
    def equity(self) -> float:
        return self.usd_total + sum(self.values.values()) + sum(self.short_value.values())

    def weights(self) -> dict:
        """Signed exposure weights: long positive, short negative."""
        eq = self.equity
        if eq <= 0:
            return {}
        w = {c: v / eq for c, v in self.values.items()}
        for c, n in self.short_notional.items():
            w[c] = w.get(c, 0.0) - n / eq
        return w

    def signed_values(self) -> dict:
        out = dict(self.values)
        for c, n in self.short_notional.items():
            out[c] = out.get(c, 0.0) - n
        return out


@dataclass
class OrderPlan:
    coin: str
    side: str      # BUY | SELL | SHORT_OPEN | SHORT_CLOSE
    qty: float     # coin quantity (spot), USD collateral (SHORT_OPEN), percent (SHORT_CLOSE)
    reason: str


def build_portfolio(balance_resp: dict, ticker: dict, shorts_resp: Optional[dict] = None) -> Portfolio:
    wallet = balance_resp.get("SpotWallet") or balance_resp.get("Wallet") or {}
    usd = wallet.get("USD", {})
    # USD "Lock" includes short collateral; that collateral is counted through each short's
    # PositionValue (collateral + unrealised PnL), so exclude it here to avoid double counting.
    locked_for_orders = float(usd.get("Lock", 0)) - float(usd.get("ShortCollateral", 0))
    pf = Portfolio(usd_free=float(usd.get("Free", 0)),
                   usd_total=float(usd.get("Free", 0)) + max(locked_for_orders, 0.0))
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
    for pos in (shorts_resp or {}).get("Positions", []) or []:
        coin = pos["Pair"].split("/")[0]
        qty = float(pos.get("ShortQty", 0))
        price = float(pos.get("CurrentPrice") or ticker.get(coin, {}).get("ask") or 0)
        pf.short_notional[coin] = pf.short_notional.get(coin, 0.0) + qty * price
        pf.short_value[coin] = pf.short_value.get(coin, 0.0) + float(pos.get("PositionValue", 0))
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
        sh = self.client.short_positions() if self.s.strategy.uses_shorts else {"Success": True, "Positions": []}
        if not ok(t) or not ok(b) or not ok(sh):
            log.error("snapshot failed: ticker=%s balance=%s shorts=%s", ok(t), ok(b), ok(sh))
            return None
        ticker = parse_ticker(t)
        return build_portfolio(b, ticker, sh), ticker

    # ------------------------------------------------------------- planning
    def qty_decimals(self, coin: str) -> int:
        return int(self.pair_info.get(coin, {}).get("AmountPrecision", 4))

    def price_decimals(self, coin: str) -> int:
        return int(self.pair_info.get(coin, {}).get("PricePrecision", 4))

    def plan(self, targets: dict, pf: Portfolio, ticker: dict, deadband_frac: float,
             min_order_usd: Optional[float] = None, reason: str = "rebalance") -> list:
        min_usd = self.cfg.min_order_usd if min_order_usd is None else min_order_usd
        eq = pf.equity
        band = max(deadband_frac * eq, min_usd)
        plans = []
        for coin in sorted(set(targets) | set(pf.values) | set(pf.short_notional)):
            px = ticker.get(coin)
            if not px or px["bid"] <= 0 or coin not in self.pair_info:
                continue
            if not self.pair_info[coin].get("CanTrade", True):
                continue
            tgt_w = targets.get(coin, 0.0)
            cur_w = (pf.values.get(coin, 0.0) - pf.short_notional.get(coin, 0.0)) / eq
            tag = f"{reason}: w {cur_w:.3f}->{tgt_w:.3f}"

            # ---- long leg
            tgt_long = max(tgt_w, 0.0) * eq
            cur_long = pf.values.get(coin, 0.0)
            diff = tgt_long - cur_long
            long_exit = tgt_long <= 0 and cur_long >= min_usd
            dec = self.qty_decimals(coin)
            if long_exit or abs(diff) >= band:
                if diff < 0:
                    free = pf.qty_free.get(coin, 0.0)
                    qty = free if tgt_long <= 0 else min(free, -diff / px["bid"])
                    qty = floor_to(min(qty, self.cfg.max_order_frac * eq / px["bid"]), dec)
                    if qty * px["bid"] >= (1.0 if long_exit else min_usd):
                        plans.append(OrderPlan(coin, "SELL", qty, tag))
                elif diff > 0:
                    qty = floor_to(min(diff, self.cfg.max_order_frac * eq) / px["ask"], dec)
                    if qty * px["ask"] >= min_usd:
                        plans.append(OrderPlan(coin, "BUY", qty, tag))

            # ---- short leg
            tgt_short = max(-tgt_w, 0.0) * eq
            cur_short = pf.short_notional.get(coin, 0.0)
            sdiff = tgt_short - cur_short
            if tgt_short <= 0 and cur_short > 0:
                plans.append(OrderPlan(coin, "SHORT_CLOSE", 100.0, tag))
            elif abs(sdiff) >= band:
                if sdiff > 0:
                    collateral = round(min(sdiff, self.cfg.max_order_frac * eq), 2)
                    if collateral >= min_usd:
                        plans.append(OrderPlan(coin, "SHORT_OPEN", collateral, tag))
                else:
                    pct = round(min(100.0, -sdiff / cur_short * 100.0), 2)
                    if pct > 0:
                        plans.append(OrderPlan(coin, "SHORT_CLOSE", pct, tag))
        return plans

    # ------------------------------------------------------------ execution
    def _send_short(self, p: OrderPlan) -> Optional[dict]:
        pair = f"{p.coin}/USD"
        if not self.s.can_trade:
            log.info("[PAPER] %s %s %.2f (%s)", p.side, pair, p.qty, p.reason)
            self.db.log_order(self.s.mode, pair, p.side, "MARKET", p.qty, None, p.reason, None)
            return {"Success": True, "Paper": True}
        if p.side == "SHORT_OPEN":
            resp = self.client.short_open(pair, f"{p.qty:.2f}")
        else:
            resp = self.client.short_close(pair, None if p.qty >= 100 else f"{p.qty:.2f}")
        self.db.log_order(self.s.mode, pair, p.side, "MARKET", p.qty, None, p.reason, resp)
        if ok(resp):
            log.info("%s %s %.2f -> %s", p.side, pair, p.qty, {k: resp.get(k) for k in
                     ("EntryPrice", "ShortQty", "ClosePrice", "RealizedPNL") if k in resp})
        else:
            log.error("%s %s rejected: %s", p.side, pair, (resp or {}).get("ErrMsg"))
        return resp

    def _send(self, p: OrderPlan, order_type: str, ticker: dict) -> Optional[dict]:
        if p.side in ("SHORT_OPEN", "SHORT_CLOSE"):
            return self._send_short(p)
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

    def _fit_to_cash(self, plans: list, pf: Portfolio, ticker: dict) -> list:
        """Scale risk-adding orders so their USD need fits free cash (no leverage)."""
        def usd(p: OrderPlan) -> float:
            return p.qty * ticker[p.coin]["ask"] if p.side == "BUY" else p.qty
        budget = pf.usd_free * (1 - 2 * self.cfg.taker_fee) - 1.0
        need = sum(usd(p) for p in plans)
        if need <= budget or need <= 0:
            return plans
        scale = max(0.0, budget / need)
        out = []
        for p in plans:
            if p.side == "BUY":
                qty = floor_to(p.qty * scale, self.qty_decimals(p.coin))
                ok_size = qty * ticker[p.coin]["ask"] >= self.cfg.min_order_usd
            else:
                qty = round(p.qty * scale, 2)
                ok_size = qty >= self.cfg.min_order_usd
            if ok_size:
                out.append(OrderPlan(p.coin, p.side, qty, p.reason + f" (scaled {scale:.2f} to cash)"))
        return out

    def _execute_group(self, sides: tuple, targets: dict, deadband: float, reason: str,
                       urgent: bool, min_order_usd: Optional[float]) -> int:
        snap = self.snapshot()
        if not snap:
            return 0
        pf, ticker = snap
        plans = [p for p in self.plan(targets, pf, ticker, deadband, min_order_usd, reason) if p.side in sides]
        if sides == ADD:
            plans = self._fit_to_cash(plans, pf, ticker)
        if not plans:
            return 0
        sent = 0
        spot = [p for p in plans if p.side in ("BUY", "SELL")]
        for p in plans:
            if p.side not in ("BUY", "SELL"):
                sent += ok(self._send(p, "MARKET", ticker))
        if urgent or not self.s.can_trade:
            for p in spot:
                sent += ok(self._send(p, "MARKET", ticker))
            return sent
        # spot: maker first
        pending = set()
        for p in spot:
            resp = self._send(p, "LIMIT", ticker)
            if ok(resp):
                sent += 1
                if resp["OrderDetail"].get("Status") == "PENDING":
                    pending.add(str(resp["OrderDetail"]["OrderID"]))
        if pending:
            self._wait_for_fills(pending)
            # anything still missing is re-planned from fresh state as MARKET
            snap = self.snapshot()
            if snap:
                pf, ticker = snap
                rest = [p for p in self.plan(targets, pf, ticker, deadband, min_order_usd,
                                             reason + " (market fallback)") if p.side in ("BUY", "SELL") and p.side in sides]
                if sides == ADD:
                    rest = self._fit_to_cash(rest, pf, ticker)
                for p in rest:
                    sent += ok(self._send(p, "MARKET", ticker))
        return sent

    def rebalance(self, targets: dict, deadband: Optional[float] = None, reason: str = "rebalance",
                  urgent: bool = False, min_order_usd: Optional[float] = None) -> int:
        deadband = self.cfg.deadband_frac if deadband is None else deadband
        n = self._execute_group(REDUCE, targets, deadband, reason, urgent, min_order_usd)
        n += self._execute_group(ADD, targets, deadband, reason, urgent, min_order_usd)
        return n

    def exit_positions(self, coins: list, reason: str) -> int:
        """Immediate MARKET exit of the given coins (stops / emergency de-risking)."""
        snap = self.snapshot()
        if not snap:
            return 0
        pf, ticker = snap
        targets = {c: w for c, w in pf.weights().items() if c not in coins}
        plans = [p for p in self.plan(targets, pf, ticker, 0.0, 1.0, reason)
                 if p.side in REDUCE and p.coin in coins]
        return sum(ok(self._send(p, "MARKET", ticker)) for p in plans)
