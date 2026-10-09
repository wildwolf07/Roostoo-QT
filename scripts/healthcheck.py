"""Pre-flight check for a new host (e.g. the EC2 instance). Read-only: no orders.

Usage: python -m scripts.healthcheck   (uses the TEST key only)
Checks: Roostoo reachability + clock skew + signed balance call, Binance klines access.
"""
from __future__ import annotations

import argparse
import sys

from bot.api.roostoo_client import RoostooClient, ok
from bot.config import load_settings
from bot.data.market_data import fetch_klines


def main() -> int:
    ap = argparse.ArgumentParser()
    # never "live": any call with the competition key must come from the bot itself
    ap.add_argument("--mode", choices=["paper", "test"], default="test")
    args = ap.parse_args()
    s = load_settings(args.mode)
    c = RoostooClient(s.api_key, s.api_secret, s.runtime.base_url)
    failures = 0

    c.sync_time()
    print(f"[{'OK' if abs(c.time_offset_ms) < 5000 else 'WARN'}] clock offset vs Roostoo: {c.time_offset_ms} ms")
    t = c.ticker()
    print(f"[{'OK' if ok(t) else 'FAIL'}] Roostoo ticker: {len((t or {}).get('Data', {}))} pairs")
    failures += not ok(t)
    b = c.balance()
    print(f"[{'OK' if ok(b) else 'FAIL'}] Roostoo signed balance ({s.mode}): "
          f"{(b or {}).get('SpotWallet', {}).get('USD') if ok(b) else (b or {}).get('ErrMsg')}")
    failures += not ok(b)
    try:
        k = fetch_klines("BTC", "1h", 5, s.runtime.binance_url)
        print(f"[OK] Binance klines: last BTC close {k['close'].iloc[-1]}")
    except Exception as exc:
        print(f"[FAIL] Binance klines: {exc}")
        failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
