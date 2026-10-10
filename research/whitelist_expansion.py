"""Should the live whitelist include more Roostoo-tradable coins? Compare the live ensemble on
the current 29 coins vs 29 + Roostoo extras (spread < ~5bp, Binance history), at universe 25/30.

Usage: python -m research.download_broad --roostoo && python -m research.whitelist_expansion
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from research.download_broad import ROOSTOO_EXTRA
from research.stress_test import combined_panel
from research.survivorship import broad_panel, run


def job(args):
    label, extra, uni = args
    close, qv, *_ = combined_panel()
    if extra:
        close, qv = broad_panel(close, qv, only=ROOSTOO_EXTRA)
    row, _ = run(close, qv, label, universe=uni)
    return row


def main() -> None:
    jobs = [("current 29, uni 25 (LIVE)", False, 25), ("current 29, uni 29", False, 29),
            ("29 + extras, uni 25", True, 25), ("29 + extras, uni 30", True, 30), ("29 + extras, uni 35", True, 35)]
    with ProcessPoolExecutor() as pool:
        rows = list(pool.map(job, jobs))
    pd.set_option("display.width", 260)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
