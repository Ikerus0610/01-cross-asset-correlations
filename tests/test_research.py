import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from lab.data import DataError, TICKERS, load_csv
from lab.stats import (
    correlation,
    downside_summary,
    pair_matrix,
    rolling_correlations,
    tail_sample,
)

ROOT = Path(__file__).resolve().parents[1]


def csv_bytes(rows):
    return pd.DataFrame(rows, columns=["date", *TICKERS]).to_csv(index=False).encode()


def row(day, price):
    return [day, *[price] * 6]


class PricesTest(unittest.TestCase):
    def test_simple_returns_sorted_and_first_date(self):
        rows = [row("2024-02-02", 99), row("2024-01-31", 100), row("2024-02-01", 110)]
        data = load_csv(csv_bytes(rows))
        np.testing.assert_allclose(
            data.returns.SPY, [np.nan, 0.10, -0.10], equal_nan=True
        )

    def test_missing_row_and_partial_quote_never_bridge(self):
        rows = [
            row(d, v)
            for d, v in zip(
                ["2024-02-01", "2024-02-02", "2024-02-06", "2024-02-07"],
                [100, 110, 120, 130],
            )
        ]
        rows[1][3] = None
        data = load_csv(csv_bytes(rows))
        self.assertEqual(list(data.missing_dates.strftime("%F")), ["2024-02-05"])
        self.assertEqual(data.missing_cells.IEF, 1)
        np.testing.assert_allclose(
            data.returns.SPY,
            [np.nan, 0.1, np.nan, np.nan, 130 / 120 - 1],
            equal_nan=True,
        )
        self.assertEqual(data.returns.IEF.count(), 1)

    def test_missing_quote_breaks_both_adjacent_returns_only_for_its_ticker(self):
        rows = [
            row(d, v)
            for d, v in zip(
                ["2024-02-05", "2024-02-06", "2024-02-07", "2024-02-08"],
                [100, 105, 110, 115],
            )
        ]
        rows[1][3] = None
        r = load_csv(csv_bytes(rows)).returns
        self.assertEqual(r.IEF.count(), 1)
        self.assertEqual(r.SPY.count(), 3)
        self.assertAlmostEqual(r.IEF.iloc[-1], 115 / 110 - 1)

    def test_weekend_holiday_and_special_closure_are_not_missing_sessions(self):
        for start, end in [("2024-05-24", "2024-05-28"), ("2025-01-08", "2025-01-10")]:
            with self.subTest(start=start):
                data = load_csv(csv_bytes([row(start, 100), row(end, 105)]))
                self.assertEqual(len(data.missing_dates), 0)
                self.assertAlmostEqual(data.returns.SPY.iloc[-1], 0.05)

    def test_invalid_prices(self):
        for bad in (0, -1, "junk", "inf", "NaN"):
            with (
                self.subTest(value=bad),
                self.assertRaisesRegex(DataError, "positive price"),
            ):
                load_csv(csv_bytes([row("2024-02-01", 100), row("2024-02-02", bad)]))

    def test_bad_dates_and_small_input(self):
        for day, msg in [
            ("2024-02-01", "Duplicate"),
            ("2024-02-03", "outside"),
            ("2024-02-30", "valid dates"),
        ]:
            with self.subTest(day=day), self.assertRaisesRegex(DataError, msg):
                load_csv(csv_bytes([row("2024-02-01", 100), row(day, 101)]))
        with self.assertRaisesRegex(DataError, "two price dates"):
            load_csv(csv_bytes([row("2024-02-01", 100)]))

    def test_format_errors(self):
        for blob in (
            b"date,SPY\n",
            b"date,SPY,SPY,IEF,UUP,GLD,USO\n",
            b"date,SPY,QQQ,IEF,UUP,GLD,USO\n2024-01-02,1,2,3\n",
        ):
            with self.subTest(blob=blob), self.assertRaises(DataError):
                load_csv(blob)


class StatisticsTest(unittest.TestCase):
    def test_perfect_positive_and_negative(self):
        x = pd.Series([1.0, 3.0, 2.0, 5.0])
        for method in ("Pearson", "Spearman"):
            for slope in (-2, 2):
                got = correlation(x, slope * x + 3, method)
                self.assertAlmostEqual(got.value, np.sign(slope))
                self.assertEqual(got.n, 4)

    def test_pairwise_counts_and_undefined(self):
        frame = pd.DataFrame(
            {"a": [1.0, np.nan, 3, 4], "b": [2.0, 4, 6, np.nan], "c": [5.0] * 4}
        )
        v, n, reasons = pair_matrix(frame, "Pearson")
        self.assertEqual(n.loc["a", "b"], 2)
        self.assertTrue(np.isnan(v.loc["a", "b"]))
        self.assertIn("Needs 3", reasons.loc["a", "b"])
        self.assertEqual(reasons.loc["c", "a"], "Zero variance")
        self.assertEqual(reasons.loc["c", "c"], "Zero variance")
        self.assertAlmostEqual(v.loc["a", "a"], 1)
        self.assertTrue(n.equals(n.T))

    def test_actual_window_lengths_and_no_lookahead(self):
        x = pd.Series(np.arange(270, dtype=float))
        for w in (20, 60, 252):
            for method in ("Pearson", "Spearman"):
                r = rolling_correlations(x, -x, w, method)
                self.assertTrue(r.iloc[: w - 1].isna().all())
                np.testing.assert_allclose(r.iloc[w - 1 :], -1)
                self.assertTrue(
                    rolling_correlations(x[: w - 1], x[: w - 1], w, method).isna().all()
                )

    def test_window_local_rank_with_ties_and_missing_values(self):
        x = pd.Series([2.0, 4.0, 4.0, 7.0, 2.0, 5.0, np.nan, 9.0, 3.0, 2.0])
        y = pd.Series([3.0, 9.0, 1.0, 2.0, 8.0, 8.0, 7.0, 1.0, 2.0, 1.0])
        result = rolling_correlations(x, y, 4, "Spearman")
        for i in range(3, 6):
            xr = x.iloc[i - 3 : i + 1].rank()
            yr = y.iloc[i - 3 : i + 1].rank()
            self.assertAlmostEqual(result.iloc[i], xr.corr(yr))
        self.assertTrue(result.iloc[6:].isna().all())

    def test_constant_rolling_series(self):
        x = pd.Series([1.0] * 25)
        self.assertTrue(rolling_correlations(x, x, 20).isna().all())

    def test_rank_cutoff_ties_fixed_and_empty(self):
        data = pd.DataFrame({"SPY": [-0.05, -0.03, -0.03] + [0.0] * 18 + [np.nan]})
        for rule, n, c in [
            ("Worst 5%", 3, -0.03),
            ("Worst 10%", 3, -0.03),
            ("Fixed decline", 1, -0.05),
        ]:
            rows, cut = tail_sample(data, rule, fall=5.0)
            self.assertEqual(len(rows), n)
            self.assertEqual(cut, c)
        self.assertTrue(tail_sample(data, "Fixed decline", fall=10)[0].empty)
        self.assertTrue(np.isnan(tail_sample(data.iloc[0:0])[1]))

    def test_five_and_ten_percent_rank_on_distinct_returns(self):
        frame = pd.DataFrame({"SPY": np.arange(-20, 20) / 1000})
        five, _ = tail_sample(frame, "Worst 5%")
        ten, _ = tail_sample(frame, "Worst 10%")
        self.assertEqual(five.index.tolist(), [0, 1])
        self.assertEqual(ten.index.tolist(), [0, 1, 2, 3])

    def test_summary_and_detail_reconciliation(self):
        s = pd.DataFrame(
            {
                "SPY": [-0.05, -0.04, -0.03, -0.02, -0.01],
                "IEF": [0.015, -0.01, np.nan, 0, 0.03],
            }
        )
        sample, _ = tail_sample(s, "Fixed decline", 1)
        result = downside_summary(sample).loc["IEF"]
        self.assertEqual(result.n, 4)
        self.assertEqual(result.positive_n, 2)
        self.assertEqual(result.positive, 0.5)
        self.assertAlmostEqual(result["mean"], 0.00875)
        self.assertAlmostEqual(result["median"], 0.0075)
        self.assertAlmostEqual(result["corr"], sample.SPY.corr(sample.IEF))

    def test_demo_winner_and_regime_shift(self):
        r = load_csv((ROOT / "data/demo_prices.csv").read_bytes()).returns
        sample, cut = tail_sample(r)
        summary = downside_summary(sample)
        self.assertEqual((r.SPY.count(), len(sample)), (1004, 51))
        self.assertEqual(summary["median"].idxmax(), "UUP")
        self.assertEqual(round(summary.loc["UUP", "median"] * 100, 2), 0.60)
        for t in TICKERS:
            self.assertEqual(summary.loc[t, "n"], sample[t].count())
            self.assertEqual(summary.loc[t, "positive_n"], (sample[t] > 0).sum())
            self.assertEqual(
                summary.loc[t, "positive"], (sample[t] > 0).sum() / sample[t].count()
            )
        early, c1 = tail_sample(r.loc[:"2022"])
        late, c2 = tail_sample(r.loc["2023":])
        self.assertNotEqual(c1, c2)
        self.assertGreater(early.IEF.median(), 0)
        self.assertLess(late.IEF.median(), 0)


if __name__ == "__main__":
    unittest.main()
