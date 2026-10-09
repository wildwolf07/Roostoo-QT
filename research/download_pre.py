"""Download 2021-01-01 -> 2023-01-10 spot hourly klines (stress-test period: LUNA, FTX, bear market)
into data/research_pre/. Usage: python -m research.download_pre"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from bot.config import ROOT, StrategyConfig
from research.download_full import SPOT, klines

OUT = ROOT / "data" / "research_pre"


def one(coin: str) -> str:
    start = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp("2023-01-10", tz="UTC").timestamp() * 1000)
    df = klines(SPOT, f"{coin}USDT", start, end)
    if df.empty:
        return f"{coin}: none"
    df = df[df.index < pd.Timestamp("2023-01-10", tz="UTC")]
    if df.empty:
        return f"{coin}: listed after the stress period"
    df.to_parquet(OUT / f"spot_{coin}.parquet")
    return f"{coin}: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for msg in pool.map(one, StrategyConfig().whitelist):
            print(msg, flush=True)


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"done in {time.time() - t:.0f}s")
