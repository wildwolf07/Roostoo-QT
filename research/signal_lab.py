"""Signal laboratory: which features predict crypto returns at our trading horizons?

For each candidate feature and forward horizon H, compute the cross-sectional rank IC
(Spearman correlation between the feature and the next-H-hour return across coins) on
non-overlapping timestamps, separately for an in-sample period and a later
out-of-sample period. A feature is only trusted if its IC has the same sign and is
significant in both periods.

Usage: python -m research.signal_lab
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from bot.config import ROOT

DATA = ROOT / "data" / "research"
SPLIT = "2025-06-01"          # in-sample before, out-of-sample after
HORIZONS = (1, 4, 8, 24, 72)
EXCLUDE = {"PAXG", "INJ", "OP", "TON", "PEPE", "SHIB"}  # gold; not on Roostoo; stale data; 18-25bp spreads
EXCLUDE |= {c for c in os.environ.get("EXTRA_EXCLUDE", "").split(",") if c}  # ad-hoc robustness runs


def load_panel():
    closes, qv, tq, fund, prem = {}, {}, {}, {}, {}
    for f in sorted(DATA.glob("spot_*.parquet")):
        coin = f.stem.split("_", 1)[1]
        if coin in EXCLUDE:
            continue
        df = pd.read_parquet(f)
        closes[coin] = df["close"]
        qv[coin] = df["quote_volume"]
        tq[coin] = df["taker_quote"]
        ff = DATA / f"funding_{coin}.parquet"
        if ff.exists():
            fund[coin] = pd.read_parquet(ff)["funding"]
        pf = DATA / f"premium_{coin}.parquet"
        if pf.exists():
            prem[coin] = pd.read_parquet(pf)["close"]
    close = pd.DataFrame(closes).sort_index()
    idx = close.index
    qv = pd.DataFrame(qv).reindex(idx)
    tq = pd.DataFrame(tq).reindex(idx)
    # funding is set every 8h: forward-fill onto the hourly grid (known at its timestamp)
    fund = pd.DataFrame(fund).sort_index()
    fund = fund[~fund.index.duplicated()].reindex(idx.union(fund.index)).ffill().reindex(idx)
    prem = pd.DataFrame(prem).reindex(idx)
    return close, qv, tq, fund, prem


def features(close, qv, tq, fund, prem) -> dict:
    logp = np.log(close)
    r1 = logp.diff()
    vol = r1.rolling(72, min_periods=48).std()
    btc = r1["BTC"]
    f = {}
    for L in (1, 4, 24):
        f[f"ret_{L}h"] = (logp - logp.shift(L)) / (vol * np.sqrt(L))
    for L in (72, 168, 336, 720):
        f[f"mom_{L}h"] = (logp - logp.shift(L)) / (vol * np.sqrt(L))
    f["mom_blend_168_336"] = (f["mom_168h"] + f["mom_336h"]) / 2
    # skip-recent momentum: 14d return excluding the last day (reversal-free momentum)
    f["mom_336h_skip24"] = (logp.shift(24) - logp.shift(336)) / (vol * np.sqrt(312))
    # order-flow imbalance from taker-buy share of quote volume
    imb = (2 * tq / qv.replace(0, np.nan) - 1)
    f["ofi_1h"] = imb
    f["ofi_24h"] = (2 * tq.rolling(24).sum() / qv.rolling(24).sum() - 1)
    # flow not explained by price move: residual of imbalance vs same-hour return (cross-section)
    f["ofi_resid_24h"] = f["ofi_24h"] - f["ofi_24h"].mean(axis=1).values[:, None]
    # funding: latest and 3-day average (crowding)
    f["funding"] = fund
    f["funding_3d"] = fund.rolling(72, min_periods=24).mean()
    # perp premium (basis) latest hour and 24h average
    f["premium_1h"] = prem
    f["premium_24h"] = prem.rolling(24, min_periods=12).mean()
    # BTC lead-lag catch-up: beta * BTC 1h return - own 1h return
    beta = r1.rolling(336, min_periods=168).cov(btc).div(btc.rolling(336, min_periods=168).var(), axis=0)
    f["btc_catchup_1h"] = beta.mul(btc, axis=0) - r1
    f["btc_catchup_4h"] = beta.mul(btc.rolling(4).sum(), axis=0) - r1.rolling(4).sum()
    # residual (idiosyncratic) momentum (Blitz, Huij & Martens 2011): strip the BTC component
    # using the previous hour's beta, normalise by residual volatility
    resid = r1 - beta.shift(1).mul(btc, axis=0)
    rvol = resid.rolling(72, min_periods=48).std()
    f["res_mom_168_336"] = (resid.rolling(168).sum() / (rvol * np.sqrt(168))
                            + resid.rolling(336).sum() / (rvol * np.sqrt(336))) / 2
    # risk characteristics
    f["vol_72h"] = vol
    f["beta_btc"] = beta
    f["max_ret_24h"] = r1.rolling(24).max()                       # lottery / MAX effect
    f["volume_shock"] = np.log(qv.rolling(24).sum() / qv.rolling(720, min_periods=240).sum() * 30)
    f["dist_high_336h"] = logp - logp.rolling(336).max()
    return f


def rank_ic(feat: pd.DataFrame, fwd: pd.DataFrame, step: int) -> pd.Series:
    a = feat.iloc[::step]
    b = fwd.reindex(a.index)
    mask = a.notna() & b.notna()
    a = a.where(mask)
    b = b.where(mask)
    ok = mask.sum(axis=1) >= 8
    return a[ok].rank(axis=1).corrwith(b[ok].rank(axis=1), axis=1).dropna()


def tstat(s: pd.Series) -> float:
    return float(s.mean() / s.std() * np.sqrt(len(s))) if len(s) > 2 and s.std() > 0 else 0.0


def main() -> None:
    close, qv, tq, fund, prem = load_panel()
    print(f"panel: {close.shape[1]} coins, {close.index[0]} -> {close.index[-1]}")
    logp = np.log(close)
    feats = features(close, qv, tq, fund, prem)
    rows = []
    for H in HORIZONS:
        fwd = logp.shift(-H) - logp
        fwd = fwd.sub(fwd.mean(axis=1), axis=0)        # relative (cross-sectional) return
        for name, x in feats.items():
            ic = rank_ic(x, fwd, step=H)
            ins, oos = ic[ic.index < SPLIT], ic[ic.index >= SPLIT]
            rows.append({"feature": name, "H": H,
                         "IC_in": ins.mean(), "t_in": tstat(ins),
                         "IC_oos": oos.mean(), "t_oos": tstat(oos), "n_oos": len(oos)})
    df = pd.DataFrame(rows)
    df["robust"] = (np.sign(df.IC_in) == np.sign(df.IC_oos)) & (df.t_in.abs() > 2) & (df.t_oos.abs() > 2)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 400)
    out = df.sort_values(["H", "t_oos"], key=lambda s: s if s.name == "H" else -s.abs())
    print(out.round(4).to_string(index=False))
    df.to_csv(ROOT / "data" / "signal_lab_ic.csv", index=False)
    print("\nROBUST (same sign, |t|>2 in both periods):")
    print(df[df.robust].sort_values("t_oos", key=abs, ascending=False).round(4).to_string(index=False))



# --------------------------------------------------------------------------- market timing
def market_features(close, qv, tq, fund, prem) -> tuple[pd.DataFrame, pd.Series]:
    """Time-series features for the equal-weight market basket."""
    logp = np.log(close)
    r1 = logp.diff()
    mkt = r1.mean(axis=1)                       # equal-weight basket hourly log return
    mlog = mkt.cumsum()
    vol = mkt.rolling(72, min_periods=48).std()
    f = {}
    for L in (4, 24, 72, 168, 336):
        f[f"mkt_ret_{L}h"] = (mlog - mlog.shift(L)) / (vol * np.sqrt(L))
    f["btc_mom_336h"] = (logp["BTC"] - logp["BTC"].shift(336))
    f["funding_avg"] = fund.mean(axis=1)
    f["funding_btc"] = fund["BTC"]
    f["funding_avg_3d"] = fund.mean(axis=1).rolling(72, min_periods=24).mean()
    f["premium_avg_24h"] = prem.mean(axis=1).rolling(24, min_periods=12).mean()
    f["ofi_mkt_24h"] = 2 * tq.sum(axis=1).rolling(24).sum() / qv.sum(axis=1).rolling(24).sum() - 1
    ema = close.ewm(span=168, adjust=False).mean()
    f["breadth_168h"] = (close > ema).mean(axis=1)
    f["vol_ratio"] = mkt.rolling(24).std() / mkt.rolling(720, min_periods=240).std()
    return pd.DataFrame(f), mlog


def timing_study(close, qv, tq, fund, prem) -> pd.DataFrame:
    feats, mlog = market_features(close, qv, tq, fund, prem)
    rows = []
    for H in (8, 24, 72):
        fwd = mlog.shift(-H) - mlog
        for name in feats.columns:
            x = feats[name].iloc[::H]
            y = fwd.reindex(x.index)
            d = pd.concat([x, y], axis=1).dropna()
            for label, part in (("in", d[d.index < SPLIT]), ("oos", d[d.index >= SPLIT])):
                if len(part) < 30:
                    continue
                c = part.iloc[:, 0].rank().corr(part.iloc[:, 1].rank())
                rows.append({"feature": name, "H": H, "period": label, "rank_corr": c,
                             "t": c * np.sqrt(len(part) - 2) / np.sqrt(max(1 - c * c, 1e-9)), "n": len(part)})
    df = pd.DataFrame(rows).pivot_table(index=["feature", "H"], columns="period", values=["rank_corr", "t"])
    df.columns = [f"{a}_{b}" for a, b in df.columns]
    return df.reset_index()


if __name__ == "__main__":
    main()
    panel = load_panel()
    ts = timing_study(*panel)
    print("\nMARKET TIMING (rank corr of feature vs forward equal-weight basket return):")
    print(ts.round(3).to_string(index=False))
    ts.to_csv(ROOT / "data" / "signal_lab_timing.csv", index=False)
