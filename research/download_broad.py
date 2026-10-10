"""Download 2021 -> now hourly spot klines for a BROAD point-in-time universe: coins that were
large at some point since 2021 but are not in our (survivor) whitelist, including coins later
delisted or renamed. Used by research/survivorship.py. Usage: python -m research.download_broad"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from bot.config import ROOT
from research.download_full import SPOT, klines

OUT = ROOT / "data" / "research_broad"
EXTRA = ("LUNC", "FTT", "MATIC", "POL", "ATOM", "ETC", "EOS", "XTZ", "ALGO", "SAND", "MANA", "AXS",
         "THETA", "VET", "FTM", "GALA", "CHZ", "EGLD", "MKR", "COMP", "SNX", "KSM", "ZIL", "ONE", "ENJ",
         "BAT", "IOTA", "NEO", "WAVES", "OP", "INJ", "TIA", "SEI", "RUNE", "GRT", "IMX", "LDO", "STX",
         "RNDR", "RENDER", "MASK", "FLOW", "KAVA")


def one(coin: str) -> str:
    start = int(pd.Timestamp("2021-01-01", tz="UTC").timestamp() * 1000)
    df = klines(SPOT, f"{coin}USDT", start, int(time.time() * 1000))
    if df.empty:
        return f"{coin}: none"
    df[["close", "quote_volume"]].to_parquet(OUT / f"spot_{coin}.parquet")
    return f"{coin}: {len(df)} bars {df.index[0].date()} -> {df.index[-1].date()}"


# Roostoo-tradable coins outside the whitelist with spread < ~5bp and Binance history
ROOSTOO_EXTRA = ("ONDO", "POL", "PENGU", "PUMP", "ASTER", "VIRTUAL", "SEI", "CAKE", "FLOKI", "ZEN", "CFX",
                 "WIF", "TRUMP", "XPL")


def main() -> None:
    import sys
    OUT.mkdir(parents=True, exist_ok=True)
    coins = ROOSTOO_EXTRA if "--roostoo" in sys.argv else EXTRA
    coins = [c for c in coins if not (OUT / f"spot_{c}.parquet").exists()]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for msg in pool.map(one, coins):
            print(msg, flush=True)


if __name__ == "__main__":
    t = time.time()
    main()
    print(f"done in {time.time() - t:.0f}s")
