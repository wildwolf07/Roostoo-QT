"""Dependency-free SVG charts for the README (docs/img/*.svg), drawn from the committed results in
results/ so every picture matches a table.

  equity.svg    growth of 100 (log scale) with an underwater (drawdown) panel: strategy vs BTC vs market
  windows.svg   distribution of 14-day returns (the contest's length): strategy vs BTC
  sleeves.svg   each sleeve alone vs the ensemble: Sharpe and Calmar
  crashes.svg   the four largest crashes in the sample
  breadth.svg   Sharpe vs universe size and coins per side (research/breadth_check.py)
  live.svg      live forward test, if results/forward_test/live_equity.csv exists

Usage: python -m research.make_results && python -m research.make_charts
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from bot.config import ROOT

OUT = ROOT / "docs" / "img"
RES = ROOT / "results"
FONT = 'font-family="-apple-system,Segoe UI,Helvetica,Arial,sans-serif"'
INK, MUTED, GRID = "#111827", "#6b7280", "#e5e7eb"
BLUE, ORANGE, GREY, GREEN, RED = "#2563eb", "#f59e0b", "#9ca3af", "#059669", "#dc2626"


def _svg(w: int, h: int, body: str, title: str, subtitle: str = "") -> str:
    sub = f'<text x="24" y="46" {FONT} font-size="12" fill="{MUTED}">{subtitle}</text>' if subtitle else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect width="100%" height="100%" fill="#ffffff"/>'
            f'<text x="24" y="28" {FONT} font-size="17" font-weight="600" fill="{INK}">{title}</text>{sub}{body}</svg>')


def _legend(items: list, x: float, y: float, gap: float = 210) -> str:
    out = ""
    for k, (label, color) in enumerate(items):
        out += (f'<rect x="{x + k * gap}" y="{y - 9}" width="14" height="4" rx="2" fill="{color}"/>'
                f'<text x="{x + k * gap + 20}" y="{y - 3}" {FONT} font-size="12" fill="{INK}">{label}</text>')
    return out


def _scale(lo: float, hi: float, a: float, b: float):
    def f(v: float) -> float:
        return a + (b - a) * (v - lo) / (hi - lo)
    return f


def _polyline(xs, ys, color: str, width: float = 2.0) -> str:
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    return f'<polyline fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" points="{pts}"/>'


def equity_chart(daily: pd.DataFrame) -> str:
    w, h = 900, 470
    x0, x1 = 64, w - 24
    top0, top1 = 70, 300          # growth panel (y pixels)
    dd0, dd1 = 330, 440           # drawdown panel
    n = len(daily)
    sx = _scale(0, n - 1, x0, x1)
    series = [("Strategy (fees included)", "strategy", BLUE, 2.4), ("BTC buy and hold", "btc", ORANGE, 1.6),
              ("Equal-weight crypto market", "equal_weight_market", GREY, 1.4)]
    norm = {k: daily[k] / daily[k].iloc[0] * 100 for _, k, _, _ in series}
    lo = math.log(min(v.min() for v in norm.values()))
    hi = math.log(max(v.max() for v in norm.values()))
    sy = _scale(lo, hi, top1, top0)
    body = ""
    for v in (25, 50, 100, 200, 400, 800):
        if lo <= math.log(v) <= hi:
            y = sy(math.log(v))
            body += (f'<line x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
                     f'<text x="{x0 - 8}" y="{y + 4:.1f}" {FONT} font-size="11" fill="{MUTED}" text-anchor="end">{v}</text>')
    idx = pd.to_datetime(daily.index)
    for yr in sorted(set(idx.year))[1:]:
        i = int(np.searchsorted(idx.values, np.datetime64(f"{yr}-01-01")))
        x = sx(i)
        body += (f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top0}" y2="{dd1}" stroke="{GRID}"/>'
                 f'<text x="{x + 4:.1f}" y="{dd1 + 16}" {FONT} font-size="11" fill="{MUTED}">{yr}</text>')
    split = int(np.searchsorted(idx.values, np.datetime64("2025-06-01")))
    unseen = int(np.searchsorted(idx.values, np.datetime64("2023-01-01")))
    body += (f'<rect x="{sx(0):.1f}" y="{top0}" width="{sx(unseen) - sx(0):.1f}" height="{dd1 - top0}" fill="#f3f4f6" opacity="0.6"/>'
             f'<text x="{sx(0) + 6:.1f}" y="{top0 + 14}" {FONT} font-size="11" fill="{MUTED}">never used for design</text>'
             f'<rect x="{sx(split):.1f}" y="{top0}" width="{x1 - sx(split):.1f}" height="{dd1 - top0}" fill="#eff6ff" opacity="0.8"/>'
             f'<text x="{sx(split) + 6:.1f}" y="{top0 + 14}" {FONT} font-size="11" fill="{BLUE}">out-of-sample</text>')
    xs = [sx(i) for i in range(n)]
    for _, k, color, width in reversed(series):
        body += _polyline(xs, [sy(math.log(v)) for v in norm[k].values], color, width)
    # drawdown panel
    sd = _scale(-0.80, 0.0, dd1, dd0)
    for v in (0.0, -0.4, -0.8):
        y = sd(v)
        body += (f'<line x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
                 f'<text x="{x0 - 8}" y="{y + 4:.1f}" {FONT} font-size="11" fill="{MUTED}" text-anchor="end">{v:.0%}</text>')
    for k, color, op in (("btc", ORANGE, 0.25), ("strategy", BLUE, 0.55)):
        dd = (daily[k] / daily[k].cummax() - 1).values
        pts = f"{xs[0]:.1f},{sd(0):.1f} " + " ".join(f"{x:.1f},{sd(v):.1f}" for x, v in zip(xs, dd)) + f" {xs[-1]:.1f},{sd(0):.1f}"
        body += f'<polygon points="{pts}" fill="{color}" opacity="{op}"/>'
    body += f'<text x="{x0}" y="{dd0 - 8}" {FONT} font-size="12" fill="{INK}">Drawdown from peak: strategy (blue) vs BTC (orange)</text>'
    body += _legend([(lab, c) for lab, _, c, _ in series], x0 + 4, top0 - 4 + 0, 250)
    return _svg(w, h, body, "Growth of 100, 2021-2026 (log scale)",
                "Live configuration, hourly rebalancing simulation, 0.1% taker fee on every fill")


def histogram_chart(daily: pd.DataFrame) -> str:
    w, h = 900, 330
    x0, x1, y0, y1 = 64, w - 24, h - 44, 64
    idx = pd.to_datetime(daily.index)
    rets = {}
    for k in ("strategy", "btc"):
        s = pd.Series(daily[k].values, index=idx)
        r, t = [], idx[0]
        while t + pd.Timedelta(days=14) <= idx[-1]:
            seg = s.loc[t: t + pd.Timedelta(days=14)]
            r.append(seg.iloc[-1] / seg.iloc[0] - 1)
            t += pd.Timedelta(days=7)
        rets[k] = np.clip(np.array(r), -0.30, 0.30)
    bins = np.linspace(-0.30, 0.30, 31)
    hs = {k: np.histogram(v, bins)[0] / len(v) for k, v in rets.items()}
    ymax = max(v.max() for v in hs.values()) * 1.1
    sx = _scale(bins[0], bins[-1], x0, x1)
    sy = _scale(0, ymax, y0, y1)
    body = ""
    for v in np.arange(0, ymax, 0.1):
        y = sy(v)
        body += (f'<line x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
                 f'<text x="{x0 - 8}" y="{y + 4:.1f}" {FONT} font-size="11" fill="{MUTED}" text-anchor="end">{v:.0%}</text>')
    for v in (-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3):
        x = sx(v)
        body += (f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y1}" y2="{y0}" stroke="{GRID if v else MUTED}"/>'
                 f'<text x="{x:.1f}" y="{y0 + 16}" {FONT} font-size="11" fill="{MUTED}" text-anchor="middle">{v:+.0%}</text>')
    bw = sx(bins[1]) - sx(bins[0])
    for k, color, op, off in (("btc", ORANGE, 0.55, 0.5), ("strategy", BLUE, 0.85, 0.0)):
        for i, frac in enumerate(hs[k]):
            if frac > 0:
                x = sx(bins[i]) + off * bw * 0.0
                body += (f'<rect x="{x + 1:.1f}" y="{sy(frac):.1f}" width="{bw - 2:.1f}" height="{y0 - sy(frac):.1f}" '
                         f'fill="{color}" opacity="{op}"/>')
    s, b = rets["strategy"], rets["btc"]
    note = (f"Strategy: {np.mean(s > 0):.0%} of windows positive, 5th percentile {np.percentile(s, 5):+.1%}.   "
            f"BTC: {np.mean(b > 0):.0%} positive, 5th percentile {np.percentile(b, 5):+.1%}.")
    body += _legend([("Strategy", BLUE), ("BTC buy and hold", ORANGE)], x0 + 4, y1 - 2, 160)
    body += f'<text x="{x1}" y="{y1 - 6}" {FONT} font-size="11" fill="{MUTED}" text-anchor="end">{note}</text>'
    return _svg(w, h, body, "Every 14-day window, 2021-2026: distribution of returns",
                "The contest is 14 days long. Weekly steps, 0.1% taker fee, clipped at ±30%")


def bars(groups: list, labels: list, colors: list, title: str, subtitle: str, fmt) -> str:
    w, h = 900, 340
    x0, x1, y0, y1 = 64, w - 24, h - 48, 78
    vals = [v for _, vs in groups for v in vs]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    span = hi - lo
    lo, hi = lo - (0.08 * span if lo < 0 else 0), hi + 0.14 * span
    sy = _scale(lo, hi, y0, y1)
    gw = (x1 - x0) / len(groups)
    bw = gw * 0.72 / len(labels)
    body = f'<line x1="{x0}" x2="{x1}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" stroke="{MUTED}"/>'
    for g, (cat, vs) in enumerate(groups):
        for k, v in enumerate(vs):
            x = x0 + g * gw + gw * 0.14 + k * bw
            top, bot = (sy(v), sy(0)) if v >= 0 else (sy(0), sy(v))
            body += (f'<rect x="{x:.1f}" y="{top:.1f}" width="{bw - 3:.1f}" height="{max(bot - top, 1):.1f}" rx="2" fill="{colors[k]}"/>'
                     f'<text x="{x + bw / 2 - 1.5:.1f}" y="{(top - 5) if v >= 0 else (bot + 13):.1f}" {FONT} font-size="11" '
                     f'fill="{INK}" text-anchor="middle">{fmt(v)}</text>')
        weight = "700" if cat.isupper() or "live" in cat.lower() else "400"
        body += (f'<text x="{x0 + g * gw + gw / 2:.1f}" y="{y0 + 20}" {FONT} font-size="12" font-weight="{weight}" '
                 f'fill="{INK}" text-anchor="middle">{cat}</text>')
    body += _legend(list(zip(labels, colors)), x0 + 4, 70, 210)
    return _svg(w, h, body, title, subtitle)


LOCKIN_STEPS = {"2026-10-11T00": "lock-in ×0.34", "2026-10-12T00": "lock-in ×0.075"}


def live_chart(live: pd.DataFrame, initial: float = 100_000.0) -> str:
    w, h = 900, 300
    x0, x1, y0, y1 = 64, w - 24, h - 44, 64
    t = pd.to_datetime(live["ts"], utc=True)
    r = live["equity"].values / initial - 1
    step = 0.0025
    lo, hi = np.floor(min(r.min(), 0.0) / step) * step - step, np.ceil(r.max() / step) * step + step
    sx = _scale(0, len(r) - 1, x0, x1)
    sy = _scale(lo, hi, y0, y1)
    body = ""
    for v in np.arange(lo, hi + 1e-9, step):
        y = sy(v)
        body += (f'<line x1="{x0}" x2="{x1}" y1="{y:.1f}" y2="{y:.1f}" stroke="{GRID}"/>'
                 f'<text x="{x0 - 8}" y="{y + 4:.1f}" {FONT} font-size="11" fill="{MUTED}" text-anchor="end">{v:+.2%}</text>')
    days = sorted(set(t.dt.floor("1D")))
    for d in days[1:]:
        i = int(np.searchsorted(t.values, np.datetime64(d.tz_localize(None))))
        body += (f'<line x1="{sx(i):.1f}" x2="{sx(i):.1f}" y1="{y1}" y2="{y0}" stroke="{GRID}"/>'
                 f'<text x="{sx(i) + 3:.1f}" y="{y0 + 16}" {FONT} font-size="11" fill="{MUTED}">{d:%b %d}</text>')
    body += f'<line x1="{x0}" x2="{x1}" y1="{sy(0):.1f}" y2="{sy(0):.1f}" stroke="{MUTED}"/>'
    for ts, label in LOCKIN_STEPS.items():
        hits = np.flatnonzero(live["ts"].values == ts)
        if len(hits):
            x = sx(int(hits[0]))
            body += (f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{y1}" y2="{y0}" stroke="{GREEN}" stroke-dasharray="4 3"/>'
                     f'<text x="{x + 4:.1f}" y="{y0 - 6}" {FONT} font-size="11" fill="{GREEN}">{label}</text>')
    body += _polyline([sx(i) for i in range(len(r))], [sy(v) for v in r], BLUE, 2.4)
    dd = (1 - live["equity"] / live["equity"].cummax()).max()
    body += (f'<text x="{x0 + 8}" y="{y0 - 10}" {FONT} font-size="13" font-weight="600" fill="{INK}">'
             f'return {r[-1]:+.2%} · max drawdown {dd:.2%}</text>')
    return _svg(w, h, body, "Live forward test: Roostoo competition account (return on $100,000)",
                f"Hourly equity since going live ({t.iloc[0]:%b %d %H:00} UTC). Dashed lines: endgame lock-in steps "
                f"(exposure cut once the gain was banked)")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    daily = pd.read_csv(RES / "backtest" / "daily_equity.csv", index_col="date")
    weekly = daily.iloc[::3]          # every third day: same picture, a light file for GitHub
    (OUT / "equity.svg").write_text(equity_chart(weekly))
    (OUT / "windows.svg").write_text(histogram_chart(daily))
    sl = pd.read_csv(RES / "backtest" / "sleeves.csv", index_col="series")
    names = {"mom_ls": "Momentum L/S", "mom_lo": "Momentum long", "mom_filtered": "Filtered mom. L/S",
             "lowrisk_lo": "Low-risk long", "ENSEMBLE": "ENSEMBLE (live)"}
    (OUT / "sleeves.svg").write_text(bars(
        [(names[k], [sl.loc[k, "sharpe"], sl.loc[k, "calmar"]]) for k in names],
        ["Sharpe ratio", "Calmar ratio"], [BLUE, GREEN],
        "Why an ensemble: each sleeve alone vs the combination (2021-2026)",
        "Low or negative correlations between sleeves lift the combined Sharpe above every component",
        fmt=lambda v: f"{v:.2f}"))
    cr = pd.read_csv(RES / "backtest" / "crash_events.csv")
    short = {"LUNA collapse": "LUNA, May 2022", "3AC/Celsius": "3AC, Jun 2022", "FTX crash": "FTX, Nov 2022",
             "Oct-10 2025 liquidation cascade": "Oct 10, 2025"}
    (OUT / "crashes.svg").write_text(bars(
        [(short.get(r.event, r.event), [100 * r.strategy, 100 * r.equal_weight_market, 100 * r.btc]) for r in cr.itertuples()],
        ["Strategy", "Equal-weight market", "BTC"], [BLUE, GREY, ORANGE],
        "The four largest crashes in the sample: return over the event (%)",
        "Hedged sleeves and volatility sizing cut crash losses to a fraction of the market's",
        fmt=lambda v: f"{v:.1f}"))
    # research/breadth_check.py (2023-2026 panel, fees included)
    (OUT / "breadth.svg").write_text(bars(
        [("15 coins", [0.86, 0.89, 0.87]), ("20 coins", [1.11, 1.14, 1.07]),
         ("25 coins (live)", [1.29, 1.27, 1.22]), ("29 coins", [1.39, 1.44, 1.37])],
        ["3 coins per side", "4 coins per side (live)", "5 coins per side"], [GREY, BLUE, GREEN],
        "Breadth: Sharpe 2023-2026 vs universe size",
        "More independent bets raise the information ratio (Grinold); coins per side barely matter",
        fmt=lambda v: f"{v:.2f}"))
    live = RES / "forward_test" / "live_equity.csv"
    if live.exists():
        (OUT / "live.svg").write_text(live_chart(pd.read_csv(live)))
    print("wrote", sorted(p.name for p in OUT.glob("*.svg")))


if __name__ == "__main__":
    main()
