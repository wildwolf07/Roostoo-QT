"""Plan B: if the top-20 cutoff is high, which mix of our (already researched) sleeves maximises
P(final return >= cutoff) and at what cost in loss risk and composite? 7.5-day stretches, 2023-26.

Usage: python -m research.plan_b
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.metrics import summary
from research.ablation import build
from research.robustness import _STATE, _init

ACTIVE_H, FLAT_H = 180, 166
MIXES = {
    "LIVE ensemble (equal 4)": {"mom_ls": .25, "mom_lo": .25, "mom_f": .25, "lowrisk_lo": .25},
    "momentum-heavy": {"mom_ls": .3, "mom_lo": .4, "mom_f": .15, "lowrisk_lo": .15},
    "long-only momentum": {"mom_lo": 1.0},
    "long-only mom + low-risk": {"mom_lo": .5, "lowrisk_lo": .5},
}


def main() -> None:
    _init()
    names = ("mom_ls", "mom_lo", "mom_f", "lowrisk_lo")
    Ws = {n: build(n)[1] for n in names}
    close = _STATE["close"]
    rets = close.pct_change(fill_method=None).fillna(0)
    flat_idx = pd.date_range("2026-10-04", periods=FLAT_H, freq="h", tz="UTC")
    act_idx = pd.date_range(flat_idx[-1] + pd.Timedelta(hours=1), periods=ACTIVE_H, freq="h", tz="UTC")
    out = []
    for label, mix in MIXES.items():
        W = sum(w * Ws[n] for n, w in mix.items())
        port = ((W.shift(1) * rets).sum(axis=1) - 0.001 * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:].values
        g = W.abs().sum(axis=1).iloc[800:].values
        for k in (1.0, 1.33, 1.6):
            rs, comps = [], []
            for s in range(0, len(port) - ACTIVE_H, 12):
                kk = min(k, 0.95 / max(g[s: s + ACTIVE_H].max(), 1e-9))
                eq_act = 1e5 * np.cumprod(1 + kk * port[s: s + ACTIVE_H])
                rs.append(eq_act[-1] / 1e5 - 1)
                if s % 48 == 0:
                    comps.append(summary(pd.Series(np.concatenate([np.full(FLAT_H, 1e5), eq_act]),
                                                   index=flat_idx.append(act_idx)))["composite"])
            rs = np.array(rs)
            out.append({"mix": label, "k": k, "P(>=2%)": f"{(rs >= .02).mean():.0%}", "P(>=3%)": f"{(rs >= .03).mean():.0%}",
                        "P(>=5%)": f"{(rs >= .05).mean():.0%}", "P(>=8%)": f"{(rs >= .08).mean():.0%}",
                        "P(loss>3%)": f"{(rs < -.03).mean():.1%}", "P(loss>5%)": f"{(rs < -.05).mean():.1%}",
                        "median comp": round(float(np.median(comps)), 2)})
    pd.set_option("display.width", 250)
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    main()
