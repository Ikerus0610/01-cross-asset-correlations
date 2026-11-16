"""Statistics use return-end dates and pairwise-complete observations."""

from dataclasses import dataclass
from math import ceil

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

MIN_CORR = 3
WINDOWS = (20, 60, 252)


@dataclass(frozen=True)
class Estimate:
    value: float
    n: int
    reason: str = ""


def correlation(x, y, method="Pearson"):
    xy = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    n = len(xy)
    if n < MIN_CORR:
        return Estimate(np.nan, n, f"Needs {MIN_CORR} paired returns")
    if (xy.nunique() <= 1).any():
        return Estimate(np.nan, n, "Zero variance")
    if method == "Spearman":
        xy = xy.rank(method="average")
    return Estimate(float(np.clip(xy.x.corr(xy.y), -1, 1)), n)


def tail_sample(returns, rule="Worst 5%", fall=1.0):
    spy = returns["SPY"].dropna()
    if rule == "Fixed decline":
        cutoff = -fall / 100
    elif len(spy):
        k = ceil(len(spy) * (0.05 if rule == "Worst 5%" else 0.10))
        cutoff = spy.nsmallest(k).iloc[-1]
    else:
        cutoff = np.nan
    return returns.loc[returns.SPY <= cutoff], cutoff


def downside_summary(sample):
    rows = []
    for asset in sample:
        r = sample[asset].dropna()
        est = correlation(sample.SPY, sample[asset])
        rows.append(
            dict(
                asset=asset,
                n=len(r),
                mean=r.mean(),
                median=r.median(),
                positive=(r > 0).mean(),
                positive_n=int((r > 0).sum()),
                corr=est.value,
                reason=est.reason,
            )
        )
    return pd.DataFrame(rows).set_index("asset")


def rolling_correlations(x, y, window, method="Pearson"):
    """Strict session windows. Rank within each window, including average ties."""
    aligned = pd.concat([x.rename("x"), y.rename("y")], axis=1)
    result = pd.Series(np.nan, index=aligned.index, dtype=float)
    if len(aligned) < window:
        return result
    wx, wy = (
        sliding_window_view(aligned[c].to_numpy(dtype=float), window)
        for c in ("x", "y")
    )
    # Bound memory even for decades of daily prices and the 252-session window.
    for start in range(0, len(wx), 1024):
        a, b = wx[start : start + 1024], wy[start : start + 1024]
        valid = (
            np.isfinite(a).all(axis=1)
            & np.isfinite(b).all(axis=1)
            & (np.ptp(a, axis=1) > 0)
            & (np.ptp(b, axis=1) > 0)
        )
        if not valid.any():
            continue
        a, b = a[valid], b[valid]
        if method == "Spearman":
            a, b = (pd.DataFrame(v).rank(axis=1).to_numpy() for v in (a, b))
        a, b = a - a.mean(axis=1, keepdims=True), b - b.mean(axis=1, keepdims=True)
        denominator = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
        values = (a * b).sum(axis=1) / denominator
        result.iloc[start + window - 1 + np.flatnonzero(valid)] = np.clip(values, -1, 1)
    return result


def pair_matrix(frame, method):
    values = pd.DataFrame(np.nan, index=frame.columns, columns=frame.columns)
    counts = pd.DataFrame(0, index=frame.columns, columns=frame.columns)
    reasons = pd.DataFrame("", index=frame.columns, columns=frame.columns)
    for i, a in enumerate(frame):
        for b in frame.columns[i:]:
            e = correlation(frame[a], frame[b], method)
            values.loc[a, b] = values.loc[b, a] = e.value
            counts.loc[a, b] = counts.loc[b, a] = e.n
            reasons.loc[a, b] = reasons.loc[b, a] = e.reason
    return values, counts, reasons
