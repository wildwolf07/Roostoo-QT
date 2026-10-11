"""Write the reproducible backtest results bundle to results/backtest/ (committed, so the numbers
can be read without downloading any data).

Strategy: the live configuration, an equal-weight ensemble of 4 sleeves on the 25 most liquid
whitelisted coins with 3 daily tranches. Weights come from the same research code that the parity
check ties to the live bot. Every fill is charged the 0.1% taker fee. Data: Binance hourly bars,
2021-02 to 2026-10. 2021-22 was never used for any design decision.

Files:
  daily_equity.csv   daily equity of the strategy, BTC and the equal-weight market (start 100,000)
  yearly.csv         return, Sharpe and max drawdown per calendar year
  windows_14d.csv    every 14-day window (weekly steps): return, max DD, Sharpe, Sortino, Calmar,
                     composite (0.4 Sortino + 0.3 Sharpe + 0.3 Calmar), and its period
  crash_events.csv   strategy vs market in the four largest crashes in the sample
  SUMMARY.md         the same tables on one page

Usage: python -m research.download_pre && python -m research.download_full && python -m research.make_results
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot.config import ROOT, StrategyConfig
from bot.metrics import max_drawdown, summary
from research.signal_lab import SPLIT, features
from research.stress_test import EVENTS, combined_panel
from research.xs_backtest import Variant, build_tranched

OUT = ROOT / "results" / "backtest"
FEE = 0.001
CRASHES = dict(EVENTS, **{"Oct-10 2025 liquidation cascade": ("2025-10-10", "2025-10-11")})


def strategy_returns(close: pd.DataFrame, qv: pd.DataFrame) -> pd.Series:
    empty = pd.DataFrame(index=close.index)
    f = features(close, qv, qv * 0.5, empty, empty)
    feats = {k: f[k] for k in ("vol_72h", "max_ret_24h", "beta_btc", "mom_blend_168_336")}
    mom = (("mom_blend_168_336", 1.0),)
    c = dict(rebalance_h=72, tranches=3, n_side=4, universe=StrategyConfig().universe_size)
    sleeves = [Variant("mom_ls", signals=mom, **c),
               Variant("mom_lo", signals=mom, long_only=True, beta_neutral=False, **c),
               Variant("mom_filtered", signals=mom, long_max_rank=0.7, short_vol_rank=0.6, **c),
               Variant("lowrisk_lo", long_only=True, **c)]
    W = sum(build_tranched(v, (close, qv), feats) for v in sleeves) / len(sleeves)
    rets = close.pct_change(fill_method=None).fillna(0)
    return ((W.shift(1) * rets).sum(axis=1) - FEE * W.diff().abs().sum(axis=1).fillna(0)).iloc[800:]


def period(t: pd.Timestamp) -> str:
    if t < pd.Timestamp("2023-01-01", tz="UTC"):
        return "2021-22 unseen"
    return "2023-25 in-sample" if t < pd.Timestamp(SPLIT, tz="UTC") else "2025-26 out-of-sample"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    close, qv, *_ = combined_panel()
    port = strategy_returns(close, qv)
    idx = port.index
    eq = (1 + port).cumprod() * 1e5
    raw = close.pct_change(fill_method=None)
    mkt = (1 + raw.mean(axis=1).fillna(0).loc[idx]).cumprod() * 1e5
    btc = close["BTC"].loc[idx].ffill()
    btc = btc / btc.iloc[0] * 1e5
    curves = {"strategy": eq, "btc": btc, "equal_weight_market": mkt}

    daily = pd.DataFrame({k: v.resample("1D").last() for k, v in curves.items()}).dropna()
    daily.index = daily.index.date
    daily.round(2).to_csv(OUT / "daily_equity.csv", index_label="date")

    rows = []
    for y in sorted(set(idx.year)):
        row = {"year": y}
        for k, v in curves.items():
            seg = v[v.index.year == y]
            d = seg.resample("1D").last().pct_change().dropna()
            row[f"{k}_return"] = round(seg.iloc[-1] / seg.iloc[0] - 1, 4)
            row[f"{k}_sharpe"] = round(d.mean() / d.std() * np.sqrt(365), 2) if d.std() > 0 else np.nan
            row[f"{k}_max_dd"] = round(max_drawdown(seg), 4)
        rows.append(row)
    yearly = pd.DataFrame(rows)
    yearly.to_csv(OUT / "yearly.csv", index=False)

    wins, t0 = [], idx[0]
    while t0 + pd.Timedelta(days=14) <= idx[-1]:
        st = summary(eq.loc[t0: t0 + pd.Timedelta(days=14)])
        wins.append({"start": t0.date(), "period": period(t0), **{k: round(st[k], 4) for k in
                     ("total_return", "max_drawdown", "sharpe", "sortino", "calmar", "composite")}})
        t0 += pd.Timedelta(days=7)
    w = pd.DataFrame(wins)
    w.to_csv(OUT / "windows_14d.csv", index=False)

    crash = []
    for name, (a, b) in CRASHES.items():
        seg = slice(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC") + pd.Timedelta(hours=23))
        crash.append({"event": name, "window": f"{a} to {b}",
                      **{k: round(v.loc[seg].iloc[-1] / v.loc[seg].iloc[0] - 1, 4) for k, v in curves.items()}})
    crashes = pd.DataFrame(crash)
    crashes.to_csv(OUT / "crash_events.csv", index=False)

    def block(seg: pd.Series) -> dict:
        st = summary(seg)
        return {"return": f"{st['total_return']:+.1%}", "Sharpe": f"{st['sharpe']:.2f}",
                "Sortino": f"{st['sortino']:.2f}", "max DD": f"{st['max_drawdown']:.1%}"}

    periods = {"2021-02 → 2022-12 (unseen)": ("2021-01-01", "2022-12-31"),
               "2023-01 → 2025-05 (in-sample)": ("2023-01-01", "2025-05-31"),
               "2025-06 → 2026-10 (out-of-sample)": ("2025-06-01", "2026-12-31"),
               "Full 2021-02 → 2026-10": ("2021-01-01", "2026-12-31")}
    lines = ["# Backtest results (generated by `python -m research.make_results`)", "",
             "Live configuration: an equal-weight ensemble of 4 sleeves, top 25 coins by volume, 3 daily",
             "tranches. Every fill pays the 0.1% taker fee. Binance hourly data. 2021-22 was never used",
             "for design. Raw files: `daily_equity.csv`, `yearly.csv`, `windows_14d.csv`, `crash_events.csv`.",
             "", "## Whole periods", "",
             "| Period | Strategy | BTC | Equal-weight market |", "|---|---|---|---|"]
    for label, (a, b) in periods.items():
        cells = []
        for v in curves.values():
            s = block(v.loc[a:b])
            cells.append(f"{s['return']}, Sharpe {s['Sharpe']}, max DD {s['max DD']}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["", "## Every 14-day window (the contest's length), weekly steps", "",
              "| Period | Windows | Median return | % positive | Median max DD | 95th pct max DD | Median composite |",
              "|---|---|---|---|---|---|---|"]
    for p, g in w.groupby("period", sort=False):
        lines.append(f"| {p} | {len(g)} | {g.total_return.median():+.2%} | {(g.total_return > 0).mean():.0%} | "
                     f"{g.max_drawdown.median():.1%} | {g.max_drawdown.quantile(0.95):.1%} | {g.composite.median():.2f} |")
    lines += ["", "## Calendar years", "", "| Year | Strategy | BTC | Equal-weight market |", "|---|---|---|---|"]
    for _, r in yearly.iterrows():
        lines.append(f"| {int(r.year)} | {r.strategy_return:+.1%} (Sharpe {r.strategy_sharpe:.2f}, DD {r.strategy_max_dd:.1%}) | "
                     f"{r.btc_return:+.1%} (DD {r.btc_max_dd:.1%}) | {r.equal_weight_market_return:+.1%} "
                     f"(DD {r.equal_weight_market_max_dd:.1%}) |")
    lines += ["", "## Crashes", "", "| Event | Window | Strategy | BTC | Equal-weight market |", "|---|---|---|---|---|"]
    for _, r in crashes.iterrows():
        lines.append(f"| {r.event} | {r.window} | {r.strategy:+.1%} | {r.btc:+.1%} | {r.equal_weight_market:+.1%} |")
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
