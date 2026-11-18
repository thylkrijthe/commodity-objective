"""Regression checks for timestamp alignment, conversions and portfolio totals."""

import unittest
from datetime import date
import pandas as pd
import numpy as np

from quotes import convert_prices
from markets import CommodityHolding, MARKETS
from portfolio import resolve_amount, values, combined, validate_lots


class AccuracyTests(unittest.TestCase):
    def test_fx_uses_prior_observation_and_reports_unmatched_latest(self):
        index = pd.to_datetime(["2026-01-05T12:05Z", "2026-01-05T12:10Z"])
        raw = pd.DataFrame({"Open": [10., 10.], "Close": [10., 10.], "share_multiplier": 1.}, index=index)
        raw.attrs["interval"] = "1 minute"
        fx = pd.Series([2., 3.], index=pd.to_datetime(["2026-01-05T12:00Z", "2026-01-05T12:10Z"]))
        actual = convert_prices(raw, "KZT", intraday_fx=fx)
        np.testing.assert_allclose(actual.Close, [20, 30])
        self.assertEqual(actual.fx_time.iloc[0], fx.index[0])
        with self.assertRaisesRegex(ValueError, "latest commodity"):
            convert_prices(raw, "KZT", intraday_fx=fx.iloc[:1].rename(
                index={fx.index[0]: fx.index[0] - pd.Timedelta(minutes=55)}))

    def test_daily_kzt_reference_is_available_only_next_day_for_intraday(self):
        raw = pd.DataFrame({"Open": [10.], "Close": [10.], "share_multiplier": 1.},
                           index=pd.to_datetime(["2026-01-06T12:00Z"]))
        raw.attrs["interval"] = "1 minute"
        rates = pd.DataFrame({"rate": [500., 550.], "provider": ["test", "test"]},
                             index=pd.to_datetime(["2026-01-05", "2026-01-06"], utc=True))
        frame = convert_prices(raw, "KZT", rates)
        self.assertEqual(frame.Close.iloc[0], 5000.)
        self.assertEqual(frame.fx_time.iloc[0], rates.index[0])

    def test_combined_portfolio_never_fills_missing_quotes(self):
        a = pd.Series([100., 110., 120.], index=pd.to_datetime(["2026-01-01","2026-01-02","2026-01-03"]))
        b = pd.Series([200., 240.], index=pd.to_datetime(["2026-01-02","2026-01-04"]))
        total = combined({"A": a, "B": b})
        self.assertEqual(total.index.tolist(), [pd.Timestamp("2026-01-02")])
        self.assertEqual(total.Total.iloc[0], 310.)

    def test_currency_amount_locks_quantity_and_shares_follow_splits(self):
        index = pd.date_range("2026-01-01", periods=3, tz="UTC")
        frame = pd.DataFrame({"Close": [100., 50., 60.], "share_multiplier": [1., 2., 2.]}, index=index)
        holding = CommodityHolding(1000., "KZT", date(2026,1,1), "Silver", "Euro amount")
        amount, baseline, multiplier = resolve_amount(frame, holding)
        self.assertEqual(amount, 10)
        self.assertEqual(values(frame, amount, baseline, multiplier).value.iloc[0], 1000)
        np.testing.assert_allclose(values(frame, 10, baseline, multiplier, True).value, [1000,1000,1200])

    def test_each_customary_and_kg_conversion(self):
        for name, spec in MARKETS.items():
            for unit in spec.units:
                holding = CommodityHolding(10, unit, date(2020,1,1), name,
                                           kg_conversion=.85 if name=="WTI crude oil" else .05)
                self.assertGreater(holding.amount, 0)
        self.assertAlmostEqual(MARKETS["Corn"].units["bushels"]*1000, 25.40117272)
        self.assertAlmostEqual(MARKETS["Wheat"].units["bushels"]*1000, 27.2155422)


if __name__ == "__main__":
    unittest.main()
