"""Regenerate the checked-in, fictional adjusted price paths (Python 3.12)."""

from pathlib import Path

import numpy as np
import pandas as pd

from lab.data import TICKERS, sessions

ROOT = Path(__file__).resolve().parents[1]


def demo_prices():
    dates = sessions("2021-01-04", "2024-12-31")
    rng = np.random.default_rng(701)
    factors = rng.standard_normal((len(dates), 6))
    equity, tech, rates, dollar, gold, oil = factors.T
    early = dates.year < 2023
    shocks = np.column_stack(
        [
            0.00025 + 0.011 * equity,
            0.0003 + 0.013 * equity + 0.005 * tech,
            0.0001 + np.where(early, -0.0055, 0.0045) * equity + 0.003 * rates,
            0.00005 - 0.0028 * equity + 0.0025 * dollar,
            0.0001 - 0.0012 * equity + 0.0065 * gold,
            0.00015 + 0.008 * equity + 0.014 * oil,
        ]
    )
    shocks[0] = 0
    return pd.DataFrame(
        100 * (1 + shocks).cumprod(axis=0), index=dates, columns=TICKERS
    )


if __name__ == "__main__":
    prices = demo_prices()
    prices.to_csv(ROOT / "data/demo_prices.csv", float_format="%.8f")
    prices.head(12).to_csv(ROOT / "data/example_prices.csv", float_format="%.8f")
    prices.head(0).to_csv(ROOT / "data/template.csv")
