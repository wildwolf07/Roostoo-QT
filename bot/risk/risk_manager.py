"""Portfolio-level and position-level risk controls.

All controls are automatic: the competition forbids manual intervention, so
every protective action must come from code.

exposure multiplier = min(drawdown brake, CPPI cap ratio, 24h loss limit) x taper x endgame lock-in
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from bot.config import RiskConfig


@dataclass
class RiskState:
    peak_equity: float = 0.0
    equity_history: deque = field(default_factory=lambda: deque(maxlen=60 * 26))  # (ts, equity)
    position_highs: dict = field(default_factory=dict)    # coin -> highest price since entry
    cooldown_until: dict = field(default_factory=dict)    # coin -> iso timestamp
    asset_daily_vol: dict = field(default_factory=dict)   # coin -> daily vol estimate

    def to_json(self) -> dict:
        return {
            "peak_equity": self.peak_equity,
            "position_highs": self.position_highs,
            "cooldown_until": self.cooldown_until,
            "asset_daily_vol": self.asset_daily_vol,
            "equity_history": [(t.isoformat(), e) for t, e in self.equity_history],
        }

    @classmethod
    def from_json(cls, d: Optional[dict]) -> "RiskState":
        s = cls()
        if not d:
            return s
        s.peak_equity = float(d.get("peak_equity", 0.0))
        s.position_highs = dict(d.get("position_highs", {}))
        s.cooldown_until = dict(d.get("cooldown_until", {}))
        s.asset_daily_vol = dict(d.get("asset_daily_vol", {}))
        for t, e in d.get("equity_history", []):
            s.equity_history.append((datetime.fromisoformat(t), float(e)))
        return s


class RiskManager:
    def __init__(self, cfg: RiskConfig, state: Optional[RiskState] = None,
                 initial_equity: Optional[float] = None):
        self.cfg = cfg
        self.state = state or RiskState()
        # CPPI floor is relative to the account's real starting equity (persisted by the bot)
        self.initial_equity = initial_equity or cfg.initial_equity

    # ----------------------------------------------------------- equity track
    def update_equity(self, equity: float, now: datetime) -> None:
        self.state.peak_equity = max(self.state.peak_equity, equity, 0.0)
        self.state.equity_history.append((now, equity))

    def drawdown(self, equity: float) -> float:
        peak = self.state.peak_equity or equity
        return max(0.0, 1.0 - equity / peak) if peak > 0 else 0.0

    def equity_24h_ago(self, now: datetime) -> Optional[float]:
        cutoff = now - timedelta(hours=24)
        past = [e for t, e in self.state.equity_history if t <= cutoff]
        if past:
            return past[-1]
        return self.state.equity_history[0][1] if self.state.equity_history else None

    # ------------------------------------------------------ exposure scaling
    def exposure_multiplier(self, equity: float, now: datetime, base_gross: float) -> tuple[float, dict]:
        c = self.cfg
        dd = self.drawdown(equity)
        if dd <= c.dd_soft:
            dd_mult = 1.0
        elif dd >= c.dd_hard:
            dd_mult = c.dd_min_mult
        else:
            frac = (dd - c.dd_soft) / (c.dd_hard - c.dd_soft)
            dd_mult = 1.0 - frac * (1.0 - c.dd_min_mult)

        floor = c.cppi_floor * self.initial_equity
        cushion = max(0.0, (equity - floor) / equity) if equity > 0 else 0.0
        cppi_cap = c.cppi_multiplier * cushion
        cppi_mult = 1.0 if base_gross <= 0 else min(1.0, cppi_cap / base_gross)

        prev = self.equity_24h_ago(now)
        day_ret = (equity / prev - 1.0) if prev else 0.0
        day_mult = c.day_loss_mult if day_ret <= -c.day_loss_limit else 1.0

        taper = c.taper_mult if now >= c.taper_start else 1.0
        banked = equity / self.initial_equity - 1.0 if self.initial_equity else 0.0
        lock = 1.0
        if c.lockin_full_at > 0 and now >= c.lockin_start:
            lock = 1.0 - (1.0 - c.lockin_min_mult) * min(1.0, max(0.0, banked / c.lockin_full_at))
        mult = max(0.0, min(dd_mult, cppi_mult, day_mult)) * taper * lock
        return mult, {
            "drawdown": round(dd, 5), "dd_mult": round(dd_mult, 3),
            "cushion": round(cushion, 5), "cppi_mult": round(cppi_mult, 3),
            "ret_24h": round(day_ret, 5), "day_mult": day_mult, "taper": taper,
            "banked": round(banked, 5), "lockin_mult": round(lock, 3), "risk_mult": round(mult, 3),
        }

    # -------------------------------------------------------- trailing stops
    def stop_distance(self, coin: str) -> float:
        vol = self.state.asset_daily_vol.get(coin, 0.04)
        return min(self.cfg.stop_max, max(self.cfg.stop_min, self.cfg.stop_vol_mult * vol))

    def check_stops(self, holdings_usd: dict, prices: dict, now: datetime, min_usd: float) -> list:
        """Update each position's best price since entry; return coins that hit their trailing stop.
        ``holdings_usd`` is signed: positive = long, negative = short."""
        if not self.cfg.stops_enabled:
            return []
        triggered = []
        for coin in list(self.state.position_highs):
            if abs(holdings_usd.get(coin, 0.0)) < min_usd:
                self.state.position_highs.pop(coin, None)  # position closed
        for coin, value in holdings_usd.items():
            price = prices.get(coin)
            if abs(value) < min_usd or not price:
                continue
            dist = self.stop_distance(coin)
            best = self.state.position_highs.get(coin, price)
            if value > 0:
                best = max(best, price)
                hit = price <= best * (1.0 - dist)
            else:
                best = min(best, price)
                hit = price >= best * (1.0 + dist)
            self.state.position_highs[coin] = best
            if hit:
                triggered.append(coin)
        return triggered

    def start_cooldown(self, coin: str, now: datetime) -> None:
        until = now + timedelta(hours=self.cfg.stop_cooldown_hours)
        self.state.cooldown_until[coin] = until.isoformat()
        self.state.position_highs.pop(coin, None)

    def blocked(self, now: datetime) -> frozenset:
        out = set()
        for coin, until in list(self.state.cooldown_until.items()):
            if datetime.fromisoformat(until) > now:
                out.add(coin)
            else:
                self.state.cooldown_until.pop(coin, None)
        return frozenset(out)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
