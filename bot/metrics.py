"""Performance metrics matching the competition's composite score:
0.4 x Sortino + 0.3 x Sharpe + 0.3 x Calmar (computed on daily returns, annualised, 365 days).
The organisers have not published the exact formula; this is our best reconstruction.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def daily_returns(equity: pd.Series) -> pd.Series:
    daily = equity.resample("1D").last().dropna()
    first = equity.iloc[0]
    return pd.concat([pd.Series([first], index=[daily.index[0] - pd.Timedelta(days=1)]), daily]).pct_change().dropna()


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float((1 - equity / peak).max())


def summary(equity: pd.Series, periods_per_year: int = 365) -> dict:
    r = daily_returns(equity)
    total = float(equity.iloc[-1] / equity.iloc[0] - 1)
    days = max((equity.index[-1] - equity.index[0]).total_seconds() / 86400, 1e-9)
    mean, std = r.mean(), r.std(ddof=1)
    downside = math.sqrt(float((np.minimum(r, 0) ** 2).mean())) if len(r) else 0.0
    sharpe = mean / std * math.sqrt(periods_per_year) if std > 0 else 0.0
    sortino = mean / downside * math.sqrt(periods_per_year) if downside > 0 else 0.0
    mdd = max_drawdown(equity)
    ann_ret = (1 + total) ** (periods_per_year / days) - 1 if total > -1 else -1.0
    calmar = ann_ret / mdd if mdd > 0 else 0.0
    return {
        "total_return": total, "max_drawdown": mdd, "sharpe": sharpe, "sortino": sortino,
        "calmar": calmar, "composite": 0.4 * sortino + 0.3 * sharpe + 0.3 * calmar,
        "days": days, "positive_days": float((r > 0).mean()) if len(r) else 0.0,
    }
