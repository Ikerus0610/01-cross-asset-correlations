"""Load and validate daily adjusted closes on the US equity session calendar."""

import csv
import io
from dataclasses import dataclass
from functools import lru_cache

import exchange_calendars as xcals
import numpy as np
import pandas as pd

PROXIES = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq-100",
    "IEF": "7–10 year US Treasuries",
    "UUP": "US dollar index futures",
    "GLD": "Gold bullion",
    "USO": "WTI crude oil futures",
}
TICKERS = list(PROXIES)


class DataError(ValueError):
    """Actionable user input error."""


@lru_cache(maxsize=8)
def sessions(start, end):
    # Padding also handles one-day ranges and weekend endpoints.
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    calendar = xcals.get_calendar(
        "XNYS", start=start - pd.Timedelta(days=10), end=end + pd.Timedelta(days=10)
    )
    return calendar.sessions_in_range(start, end).rename("date")


@dataclass
class Dataset:
    prices: pd.DataFrame
    returns: pd.DataFrame
    missing_dates: pd.DatetimeIndex
    missing_cells: pd.Series


def daily_returns(prices):
    """Input must already be indexed to every expected session."""
    return prices.div(prices.shift(1)).sub(1)


def load_csv(blob: bytes) -> Dataset:
    try:
        raw = blob.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(raw)), [])
        if len(header) != len(set(header)) or set(header) != {"date", *TICKERS}:
            raise DataError(
                "Required unique columns: date, " + ", ".join(TICKERS) + "."
            )
        # Reject ragged records, including extra fields pandas might infer as an index.
        for line, row in enumerate(csv.reader(io.StringIO(raw), strict=True), 1):
            if row and len(row) != len(header):
                raise DataError(
                    f"Row {line} has {len(row)} fields. Expected {len(header)}."
                )
        frame = pd.read_csv(io.StringIO(raw), dtype=str, keep_default_na=False)
    except (UnicodeDecodeError, csv.Error, pd.errors.ParserError) as exc:
        raise DataError(
            "Use a comma-separated UTF-8 CSV with one price per field."
        ) from exc
    if frame.empty or not frame.date.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
        raise DataError("Supply price rows with dates in YYYY-MM-DD format.")
    dates = pd.DatetimeIndex(
        pd.to_datetime(frame.date, format="%Y-%m-%d", errors="coerce")
    )
    if dates.hasnans or dates.min().year < 1993 or dates.max().year > 2100:
        raise DataError(
            "Use valid dates between 1993 and 2100 (US ETF session calendar)."
        )
    if dates.has_duplicates:
        bad = dates[dates.duplicated()][0].date()
        raise DataError(f"Duplicate date: {bad}. Supply one row per session.")
    if len(dates) < 2:
        raise DataError("At least two price dates are required to compute one return.")
    values = (
        frame[TICKERS]
        .apply(lambda col: col.str.strip())
        .replace({"": np.nan, "NA": np.nan, "N/A": np.nan})
    )
    prices = values.apply(pd.to_numeric, errors="coerce")
    invalid = values.notna() & (~np.isfinite(prices) | (prices <= 0))
    if invalid.any().any():
        i, j = np.argwhere(invalid.to_numpy())[0]
        raise DataError(
            f"{TICKERS[j]} on {dates[i].date()}: enter a finite positive price or leave it blank."
        )
    prices.index = dates
    expected = sessions(dates.min(), dates.max())
    off = dates.difference(expected)
    if len(off):
        raise DataError(
            f"{off[0].date()} is outside the US equity trading calendar (XNYS)."
        )
    missing_dates = expected.difference(dates)
    missing_cells = prices.isna().sum()
    prices = prices.reindex(expected)
    returns = daily_returns(prices)
    if np.isinf(returns).any().any():
        raise DataError(
            "Prices imply an unrepresentable return. Check price units and decimals."
        )
    return Dataset(prices, returns, missing_dates, missing_cells)
