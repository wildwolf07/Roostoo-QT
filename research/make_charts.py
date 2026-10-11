"""Generate dependency-free SVG charts for the README (docs/img/*.svg).

Usage: python -m research.make_charts
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from bot.config import ROOT, StrategyConfig
from research.signal_lab import features
from research.stress_test import combined_panel
from research.xs_backtest import Variant, build_tranched

OUT = ROOT / "docs" / "img"
W, H, PAD = 760, 340, 56
FONT = 'font-family="Helvetica,Arial,sans-serif"'
INK, MUTED, GRID = "#1f2937", "#6b7280", "#e5e7eb"
BLUE, ORANGE, GREEN, RED = "#2563eb", "#f59e0b", "#059669", "#dc2626"


def _svg(body: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f'<rect width="100%" height="100%" fill="#ffffff"/>'
            f'<text x="{PAD}" y="26" {FONT} font-size="16" font-weight="600" fill="{INK}">{title}</text>{body}</svg>')


def line_chart(series: dict, title: str, log: bool = True, fmt=lambda v: f"{v:.0f}") -> str:
    idx = next(iter(series.values())).index
    vals = np.concatenate([s.values for s in series.values()])
    f = (lambda v: math.log(v)) if log else (lambda v: v)
    lo, hi = f(vals.min()), f(vals.max())
    x0, x1, y0, y1 = PAD, W - 20, H - 40, 44
    sx = lambda i: x0 + (x1 - x0) * i / (len(idx) - 1)
    sy = lambda v: y0 - (y0 - y1) * (f(v) - lo) / (hi - lo)
    body = ""
    for k in range(5):
        v = math.exp(lo + (hi - lo) * k / 4) if log else lo + (hi - lo) * k / 4
        y = sy(v)
        body += (f'<line x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
                 f'<text x="{x0 - 6}" y="{y + 4:.1f}" {FONT} font-size="11" fill="{MUTED}" text-anchor="end">{fmt(v)}</text>')
    years = sorted({d.year for d in idx})
    for yv in years:
        i = idx.searchsorted(pd.Timestamp(f"{yv}-01-01", tz=idx.tz))
        if 0 < i < len(idx):
            body += (f'<line x1="{sx(i):.1f}" x2="{sx(i):.1f}" y1="{y0}" y2="{y1}" stroke="{GRID}"/>'
                     f'<text x="{sx(i) + 3:.1f}" y="{y0 + 16}" {FONT} font-size="11" fill="{MUTED}">{yv}</text>')
    colors = [BLUE, ORANGE, GREEN, RED]
    for n, (name, s) in enumerate(series.items()):
        pts = " ".join(f"{sx(i):.1f},{sy(v):.1f}" for i, v in enumerate(s.values))
        body += f'<polyline fill="none" stroke="{colors[n]}" stroke-width="2" points="{pts}"/>'
        body += (f'<rect x="{x0 + 10 + n * 260}" y="{y1 + 4}" width="12" height="3" fill="{colors[n]}"/>'
                 f'<text x="{x0 + 28 + n * 260}" y="{y1 + 9}" {FONT} font-size="12" fill="{INK}">{name}</text>')
    return _svg(body, title)


def bar_chart(groups: list, labels: list, title: str, fmt=lambda v: f"{v:.2f}", colors=(BLUE, ORANGE, GREEN)) -> str:
    """groups: list of (category, [values per label])"""
    vals = [v for _, vs in groups for v in vs]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    span = hi - lo
    lo, hi = lo - (0.06 * span if lo < 0 else 0), hi + 0.12 * span
    x0, x1, y0, y1 = PAD, W - 20, H - 44, 56
    sy = lambda v: y0 - (y0 - y1) * (v - lo) / (hi - lo)
    gw = (x1 - x0) / len(groups)
    bw = gw * 0.7 / len(labels)
    body = f'<line x1="{x0}" x2="{x1}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" stroke="{MUTED}"/>'
    for g, (cat, vs) in enumerate(groups):
        for k, v in enumerate(vs):
            x = x0 + g * gw + gw * 0.15 + k * bw
            top, bot = (sy(v), sy(0)) if v >= 0 else (sy(0), sy(v))
            body += (f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw - 2:.1f}" height="{max(bot - top, 1):.1f}" fill="{colors[k]}"/>'
                     f'<text x="{x + bw / 2 - 1:.1f}" y="{(top - 4) if v >= 0 else (bot + 12):.1f}" {FONT} font-size="10" '
                     f'fill="{INK}" text-anchor="middle">{fmt(v)}</text>')
        body += (f'<text x="{x0 + g * gw + gw / 2:.1f}" y="{y0 + 18}" {FONT} font-size="12" fill="{INK}" '
                 f'text-anchor="middle">{cat}</text>')
    for k, lab in enumerate(labels):
        body += (f'<rect x="{x0 + 10 + k * 230}" y="{36}" width="12" height="10" fill="{colors[k]}"/>'
                 f'<text x="{x0 + 28 + k * 230}" y="{45}" {FONT} font-size="12" fill="{INK}">{lab}</text>')
    return _svg(body, title)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    close, qv, tq, fund, prem = combined_panel()
    f = features(close, qv, qv * 0.5, fund, prem)
    feats = {k: f[k] for k in ("vol_72h", "max_ret_24h", "beta_btc", "mom_blend_168_336")}
    mom = (("mom_blend_168_336", 1.0),)
    c = dict(rebalance_h=72, tranches=3, n_side=4, universe=StrategyConfig().universe_size)
    sleeves = [Variant("a", signals=mom, **c), Variant("b", signals=mom, long_only=True, beta_neutral=False, **c),
               Variant("c", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, **c), Variant("d", long_only=True, **c)]
    Wt = sum(build_tranched(v, (close, qv), feats) for v in sleeves) / 4
    rets = close.pct_change(fill_method=None).fillna(0)
    port = ((Wt.shift(1) * rets).sum(axis=1) - 0.001 * Wt.diff().abs().sum(axis=1).fillna(0)).iloc[800:]
    eq = (1 + port).cumprod().resample("1D").last() * 100
    btc = close["BTC"].reindex(eq.index, method="ffill")
    btc = btc / btc.iloc[0] * 100
    (OUT / "equity.svg").write_text(line_chart(
        {"Ensemble (fees incl.)": eq, "BTC buy and hold": btc},
        "Growth of 100: ensemble vs BTC, 2021-2026 (log scale)", log=True))
    (OUT / "breadth.svg").write_text(bar_chart(
        [("15 coins", [0.86, 0.89, 0.87]), ("20 coins", [1.11, 1.14, 1.07]),
         ("25 coins (live)", [1.29, 1.27, 1.22]), ("29 coins", [1.39, 1.44, 1.37])],
        ["3 coins/side", "4 coins/side", "5 coins/side"],
        "Breadth: Sharpe 2023-2026 vs universe size (fees incl.)"))
    (OUT / "crashes.svg").write_text(bar_chart(
        # values from results/backtest/crash_events.csv (python -m research.make_results)
        [("LUNA 2022", [-6.5, -30.1, -18.6]), ("3AC 2022", [-4.1, -26.1, -30.9]),
         ("FTX 2022", [-1.5, -22.4, -17.5]), ("Oct-10 2025", [-2.0, -20.4, -9.1])],
        ["Ensemble", "Equal-weight market", "BTC"],
        "Crash windows: return (%)", fmt=lambda v: f"{v:.1f}", colors=(BLUE, MUTED, ORANGE)))
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
