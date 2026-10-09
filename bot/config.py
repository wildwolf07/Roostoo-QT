"""Central configuration.

Every tunable number lives here so a strategy change is always a visible,
committed diff. Secrets come only from the environment (.env, gitignored).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env loader (avoids an extra dependency). Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class StrategyConfig:
    # Universe: liquid crypto majors that also trade on Binance (for OHLCV history).
    # Tokenized stocks and thin meme coins are excluded on purpose.
    whitelist: tuple = (
        "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "SUI", "LTC", "DOT",
        "NEAR", "TRX", "UNI", "AAVE", "HBAR", "XLM", "APT", "ARB", "FET", "ENA", "ZEC", "TAO",
        "FIL", "ICP", "CRV", "PENDLE", "WLD",
    )   # PEPE/SHIB removed: 18-25bp tick-size spreads on Roostoo; ensemble Sharpe improved without them
    universe_size: int = 25            # top-N of whitelist by 24h USD volume (breadth study: 15->25 lifts Sharpe 0.89->1.27)
    bar_interval: str = "1h"
    history_bars: int = 500            # hourly bars fetched for indicators (>= 336 + tranche offsets)

    # Regime (BTC as market factor)
    regime_fast_ema: int = 24
    regime_slow_ema: int = 72

    # Momentum: vol-normalised returns averaged over several lookbacks (hours)
    mom_lookbacks: tuple = (168, 336)  # 7d and 14d: short lookbacks mean-revert (see RESEARCH.md)
    vol_lookback: int = 72
    max_positions: int = 4
    rebalance_hours: int = 24          # scheduled rebalance every N hours (UTC-aligned)
    hold_rank_buffer: int = 0          # hysteresis: keep a held coin while rank < max_positions + buffer
    # "trend": regime-gated long momentum (+ optional RISK_OFF short sleeve)
    # "xs": cross-sectional momentum, long the strongest / short the weakest, near market-neutral
    # "blend": 50/50 average of the two styles above
    # "ensemble": 4 equal sleeves (momentum L/S, momentum long, filtered momentum L/S, low-risk long)
    style: str = "ensemble"
    ensemble_n: int = 4                # coins per side in each ensemble sleeve
    lottery_max_rank: float = 0.7      # filtered sleeve: longs must rank <= 70th pct on 24h MAX return
    short_vol_rank: float = 0.6        # filtered sleeve: shorts must rank <= 60th pct on volatility
    # Tranching: average the targets computed at t, t-spacing, t-2*spacing, ... so the book
    # behaves like overlapping sub-portfolios (daily trades, slow turnover, less timing luck)
    tranches: int = 3
    tranche_spacing_hours: int = 24
    xs_net_bias: float = 0.0           # xs only: net exposure tilt per regime unit (0 = neutral)
    use_regime_gate: bool = False      # trend only: scale longs by BTC regime (added no value in tests)
    # Short sleeve: in RISK_OFF, short the weakest coins (Roostoo /v6 shorts, 0.1% fee each way)
    enable_shorts: bool = False
    short_max_positions: int = 3
    short_max_gross: float = 0.6
    short_exclude: tuple = ("PAXG",)

    @property
    def uses_shorts(self) -> bool:
        return self.enable_shorts or self.style in ("xs", "blend", "ensemble")

    # Sizing
    target_daily_vol: float = 0.012    # portfolio daily vol target (1.2%)
    max_weight: float = 0.30           # per-asset cap
    max_gross: float = 0.95            # never fully invested; no leverage
    min_gross: float = 0.0             # optional always-on core sleeve (off: it lost money in tests)
    core_asset: str = "BTC"            # core sleeve used when nothing qualifies


@dataclass(frozen=True)
class RiskConfig:
    initial_equity: float = 100_000.0
    # Settings chosen by research/overlay_study.py: tight brakes (CPPI 96% floor, 1.5-4.5% brake,
    # 24h limit) whipsawed - cut exposure after small dips and missed rebounds (OOS median
    # composite -0.78 vs +2.70 for the loose brake below). Keep only a loose disaster brake.
    # Drawdown brake: linear de-risking between these drawdowns from peak.
    dd_soft: float = 0.025
    dd_hard: float = 0.07
    dd_min_mult: float = 0.25
    # CPPI-style cap: max gross = multiplier * cushion above floor (floor 0 = disabled).
    cppi_floor: float = 0.0            # fraction of initial equity
    cppi_multiplier: float = 15.0
    # Rolling 24h loss limit (1.0 = disabled)
    day_loss_limit: float = 1.0
    day_loss_mult: float = 0.5
    # Per-position trailing stop from the high since entry: disaster-only, wide enough not to
    # trigger on ordinary noise (a 3-day holding period at ~3-6% daily coin vol)
    stop_vol_mult: float = 4.0         # x daily vol of the asset
    stop_min: float = 0.06
    stop_max: float = 0.15
    stop_cooldown_hours: int = 6
    # End-of-competition taper (UTC)
    taper_start: datetime = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
    taper_mult: float = 0.5


@dataclass(frozen=True)
class ExecutionConfig:
    deadband_frac: float = 0.02        # min |target-current| as fraction of equity
    min_order_usd: float = 200.0
    daily_rebalance_deadband: float = 0.005
    limit_timeout_sec: int = 180       # maker order wait before market fallback
    max_order_frac: float = 0.35       # single order notional cap vs equity
    max_price_deviation: float = 0.03  # reject orders far from current ticker
    taker_fee: float = 0.001
    maker_fee: float = 0.0005


@dataclass(frozen=True)
class RuntimeConfig:
    base_url: str = "https://mock-api.roostoo.com"
    binance_url: str = "https://data-api.binance.vision"
    loop_seconds: int = 60
    max_calls_per_minute: int = 20     # exchange limit is 30; keep headroom
    db_path: Path = ROOT / "data" / "bot.db"
    log_dir: Path = ROOT / "logs"
    # Competition key refuses to run before this time (UTC).
    live_start: datetime = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)
    live_end: datetime = datetime(2026, 10, 17, 23, 59, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Settings:
    mode: str
    api_key: str
    api_secret: str
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    @property
    def can_trade(self) -> bool:
        return self.mode in ("test", "live")


def load_settings(mode: str | None = None) -> Settings:
    load_dotenv()
    mode = (mode or os.environ.get("MODE", "paper")).lower()
    if mode not in ("paper", "test", "live"):
        raise ValueError(f"MODE must be paper|test|live, got {mode!r}")
    # paper mode reads data with the test key but never sends orders
    prefix = "ROOSTOO_LIVE" if mode == "live" else "ROOSTOO_TEST"
    key = os.environ.get(f"{prefix}_API_KEY", "")
    secret = os.environ.get(f"{prefix}_API_SECRET", "")
    if not key or not secret:
        raise RuntimeError(f"Missing {prefix}_API_KEY / {prefix}_API_SECRET in environment")
    settings = Settings(mode=mode, api_key=key, api_secret=secret)
    if mode == "live":
        now = datetime.now(timezone.utc)
        if now < settings.runtime.live_start:
            raise RuntimeError("Competition key may not be used before the competition starts")
    return settings
