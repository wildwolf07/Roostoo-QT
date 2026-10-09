"""Market data.

Roostoo gives live ticker snapshots only (no OHLCV). Its prices are streamed
from Binance, so indicator history comes from Binance public klines
(data-api.binance.vision: free, no key, not subject to Roostoo's rate limit).
"""
from __future__ import annotations

import logging
import time
from typing import Iterable, Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume", "close_time",
    "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
]


def to_binance_symbol(coin: str) -> str:
    return f"{coin}USDT"


def fetch_klines(coin: str, interval: str = "1h", limit: int = 400,
                 base_url: str = "https://data-api.binance.vision",
                 start_ms: Optional[int] = None, end_ms: Optional[int] = None,
                 session: Optional[requests.Session] = None) -> pd.DataFrame:
    params = {"symbol": to_binance_symbol(coin), "interval": interval, "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms
    http = session or requests
    r = http.get(f"{base_url}/api/v3/klines", params=params, timeout=15)
    r.raise_for_status()
    df = pd.DataFrame(r.json(), columns=KLINE_COLUMNS)
    if df.empty:
        return df
    for col in ("open", "high", "low", "close", "volume", "quote_volume"):
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df.set_index("open_time")


def closed_bars_only(df: pd.DataFrame, now: Optional[pd.Timestamp] = None) -> pd.DataFrame:
    now = now or pd.Timestamp.now(tz="UTC")
    return df[df["close_time"] < now]


class MarketData:
    def __init__(self, base_url: str, interval: str = "1h", history_bars: int = 400):
        self.base_url = base_url
        self.interval = interval
        self.history_bars = history_bars
        self.session = requests.Session()

    def hourly_closes(self, coins: Iterable[str]) -> pd.DataFrame:
        """Closed hourly bars for each coin, aligned into one DataFrame (columns = coins)."""
        series = {}
        for coin in coins:
            for attempt in range(3):
                try:
                    df = fetch_klines(coin, self.interval, self.history_bars, self.base_url,
                                      session=self.session)
                    series[coin] = closed_bars_only(df)["close"]
                    break
                except Exception as exc:  # network / HTTP errors
                    log.warning("klines %s failed (%s), attempt %d", coin, exc, attempt + 1)
                    time.sleep(1 + attempt)
        if not series:
            return pd.DataFrame()
        return pd.DataFrame(series).sort_index()


def parse_ticker(resp: dict) -> dict:
    """{'BTC': {'bid':..,'ask':..,'last':..,'volume_usd':..}, ...} for */USD pairs."""
    out = {}
    for pair, d in (resp or {}).get("Data", {}).items():
        coin, _, quote = pair.partition("/")
        if quote != "USD":
            continue
        out[coin] = {
            "bid": float(d.get("MaxBid") or 0),
            "ask": float(d.get("MinAsk") or 0),
            "last": float(d.get("LastPrice") or 0),
            "change_24h": float(d.get("Change") or 0),
            "volume_usd": float(d.get("UnitTradeValue") or 0),
        }
    return out


def select_universe(ticker: dict, whitelist: Iterable[str], size: int, must_include=("BTC",)) -> list:
    """Top-``size`` whitelisted coins by 24h USD volume on Roostoo."""
    ranked = sorted((c for c in whitelist if c in ticker and ticker[c]["last"] > 0),
                    key=lambda c: ticker[c]["volume_usd"], reverse=True)
    chosen = ranked[:size]
    for c in must_include:
        if c not in chosen and c in ticker:
            chosen.append(c)
    return chosen
