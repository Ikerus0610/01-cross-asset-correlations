from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


class AppFlowTest(unittest.TestCase):
    def setUp(self):
        prices = pd.read_csv(APP.parent / "data/demo_prices.csv", parse_dates=["date"]).set_index("date")
        response = pd.concat({"Adj Close": prices, "Close": prices * 2}, axis=1)
        from lab.yahoo import download_prices
        download_prices.clear()
        mock = patch("lab.yahoo.yf.download", return_value=response)
        mock.start()
        self.addCleanup(mock.stop)
        self.addCleanup(download_prices.clear)
        self.at = AppTest.from_file(str(APP), default_timeout=20).run()

    def test_default_header_and_detail_match(self):
        at = self.at
        self.assertFalse(at.exception)
        self.assertIn("UUP", at.subheader[0].value)
        self.assertIn("+0.60%", at.subheader[0].value)
        self.assertIn("51 sessions", at.expander[0].label)
        detail, summary = at.main.dataframe
        self.assertEqual(len(detail.value), 51)
        self.assertEqual(summary.value.loc["UUP", "Valid days"], len(detail.value))
        self.assertEqual(summary.value.loc["UUP", "Positive %"], "100.0%")

    def test_comparison_and_fixed_no_matches(self):
        at = self.at
        at.toggle[0].set_value(True).run()
        self.assertEqual([len(df.value) for df in at.main.dataframe[:2]], [26, 26])
        at.selectbox[0].select("Fixed decline").run()
        at.number_input[0].set_value(95.0).run()
        self.assertIn("No qualifying returns", [s.value for s in at.subheader])
        self.assertFalse(at.exception)

    def test_pair_and_date_change(self):
        at = self.at
        at.radio(key="navigation").set_value("Pair explorer").run()
        first, second, method = at.main.selectbox
        first.select("GLD").run()
        at.main.selectbox[1].select("USO").run()
        at.main.selectbox[2].select("Spearman").run()
        at.date_input[0].set_value((date(2024, 1, 2), date(2024, 3, 28))).run()
        table = at.main.dataframe[0].value
        self.assertIn("GLD × USO", [s.value for s in at.subheader])
        self.assertTrue(table.iloc[0]["Valid pairs"] > 20)
        self.assertEqual(table.iloc[1]["Valid pairs"], 20)
        self.assertEqual(table.iloc[-1]["Correlation"], "N/D")
        self.assertFalse(at.exception)

    def test_matrix_downside_small_sample(self):
        at = self.at
        at.radio(key="navigation").set_value("Correlation matrix").run()
        at.main.radio[1].set_value("SPY downside sessions").run()
        at.date_input[0].set_value((date(2024, 1, 2), date(2024, 1, 4))).run()
        reasons = at.main.dataframe[0].value
        self.assertTrue((reasons["Valid pairs"] == 1).all())
        self.assertTrue(reasons["Reason"].str.contains("Needs 3").all())
        self.assertFalse(at.exception)
