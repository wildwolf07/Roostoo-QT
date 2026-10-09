"""Confirm the breadth effect: universe size x coins-per-side grid for the ensemble."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from bot.config import ROOT
from research.robustness import _init, run


def main() -> None:
    import os
    sizes = tuple(int(x) for x in os.environ.get("UNI_SIZES", "15,20,25,31").split(","))
    grid = [(f"uni={u} n={n}", {"uni": u, "n": n}) for u in sizes for n in (3, 4, 5)]
    with ProcessPoolExecutor(initializer=_init) as pool:
        rows = list(pool.map(run, grid))
    df = pd.DataFrame(rows)
    cols = ["variant", "IS_med_comp", "OOS_med_comp", "IS_p>0", "OOS_p>0", "OOS_med_mdd%", "full_sharpe",
            "full_ret%", "full_mdd%", "turnover/day", "SR_2023", "SR_2024", "SR_2025", "SR_2026"]
    pd.set_option("display.width", 250)
    print(df[cols].round(3).to_string(index=False))
    df.to_csv(ROOT / "data" / "breadth_check.csv", index=False)


if __name__ == "__main__":
    main()
