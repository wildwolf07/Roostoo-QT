"""Download the research dataset (Binance public data, 2023 -> now) into data/research/.

- spot 1h klines incl. taker-buy volume (order-flow imbalance)
- USD-M perpetual funding rates (8h)
- USD-M perpetual premium index 1h klines (perp vs spot basis)

Usage: python -m research.download_full [--start 2023-01-01]
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from bot.config import ROOT, StrategyConfig

OUT = ROOT / "data" / "research"
SPOT = "https://data-api.binance.vision/api/v3/klines"
FUT = "https://fapi.binance.com"
COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
        "trades", "taker_base", "taker_quote", "ignore"]


def _get(url: str, params: dict, tries: int = 5):
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429):
                time.sleep(10 * (i + 1))
                continue
            return None
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    return None


def klines(url: str, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows, cursor = [], start_ms
    while cursor < end_ms:
        data = _get(url, {"symbol": symbol, "interval": "1h", "limit": 1000, "startTime": cursor})
        if not data:
            break
        rows.extend(data)
        nxt = int(data[-1][6]) + 1
        if nxt <= cursor or len(data) < 1000:
            break
        cursor = nxt
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=COLS[: len(rows[0])] if len(rows[0]) <= len(COLS) else None)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.drop_duplicates("open_time").set_index("open_time")
    for c in df.columns:
        if c not in ("close_time",):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.drop(columns=["close_time", "ignore"], errors="ignore")


def funding(symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows, cursor = [], start_ms
    while cursor < end_ms:
        data = _get(f"{FUT}/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1000, "startTime": cursor})
        if not data:
            break
        rows.extend(data)
        nxt = int(data[-1]["fundingTime"]) + 1
        if len(data) < 1000 or nxt <= cursor:
            break
        cursor = nxt
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df["funding"] = pd.to_numeric(df["fundingRate"], errors="coerce")
    return df.drop_duplicates("time").set_index("time")[["funding"]]


def one(coin: str, start_ms: int, end_ms: int) -> str:
    sym = f"{coin}USDT"
    out = []
    spot = klines(SPOT, sym, start_ms, end_ms)
    if not spot.empty:
        spot.to_parquet(OUT / f"spot_{coin}.parquet")
        out.append(f"spot {len(spot)}")
    fr = funding(sym, start_ms, end_ms)
    if not fr.empty:
        fr.to_parquet(OUT / f"funding_{coin}.parquet")
        out.append(f"funding {len(fr)}")
    prem = klines(f"{FUT}/fapi/v1/premiumIndexKlines", sym, start_ms, end_ms)
    if not prem.empty:
        prem[["open", "high", "low", "close"]].to_parquet(OUT / f"premium_{coin}.parquet")
        out.append(f"premium {len(prem)}")
    return f"{coin}: " + ", ".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    start_ms = int(pd.Timestamp(args.start, tz="UTC").timestamp() * 1000)
    end_ms = int(time.time() * 1000)
    coins = list(StrategyConfig().whitelist) + ["TON", "OP", "INJ", "WLD", "PEPE", "SHIB", "FIL", "ICP", "CRV", "PENDLE"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for msg in pool.map(lambda c: one(c, start_ms, end_ms), coins):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
