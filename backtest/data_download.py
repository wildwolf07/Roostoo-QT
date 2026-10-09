"""Download Binance hourly klines for the strategy whitelist into data/klines/*.csv.

Usage: python -m backtest.data_download --days 540
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from bot.config import ROOT, StrategyConfig
from bot.data.market_data import fetch_klines

OUT = ROOT / "data" / "klines"


def download(coin: str, days: int) -> pd.DataFrame:
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    frames = []
    cursor = start
    while cursor < end:
        df = fetch_klines(coin, "1h", 1000, start_ms=cursor)
        if df.empty:
            break
        frames.append(df)
        cursor = int(df["close_time"].iloc[-1].timestamp() * 1000) + 1
        time.sleep(0.2)
    data = pd.concat(frames)
    return data[~data.index.duplicated()][["open", "high", "low", "close", "volume", "quote_volume"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=540)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    for coin in StrategyConfig().whitelist:
        df = download(coin, args.days)
        df.to_csv(OUT / f"{coin}.csv")
        print(f"{coin}: {len(df)} bars {df.index[0]} -> {df.index[-1]}")


if __name__ == "__main__":
    main()
