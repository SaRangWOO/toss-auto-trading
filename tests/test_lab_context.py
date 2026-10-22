from copy import deepcopy
from datetime import datetime, timedelta
import unittest
from test_paper_lab import bars, book, frame
from toss_trader.lab_context import market_context
from toss_trader.lab_data import KST


class MarketContextTests(unittest.TestCase):
    def fixture(self):
        stock = bars()
        index = deepcopy(stock)
        for row in index:
            row["timestamp"] = (datetime.fromisoformat(row["timestamp"])-timedelta(minutes=1)).isoformat()
            row.update(openPrice="100", highPrice="100", lowPrice="100", closePrice="100")
        index[-1].update(openPrice="99", highPrice="99", lowPrice="99", closePrice="99")
        return stock, {"market_bars": {"KOSPI": index, "KOSDAQ": deepcopy(index)},
                       "market_observed_at": {s: "2026-10-08T09:40:05+09:00" for s in ("KOSPI", "KOSDAQ")}}

    def test_aligned_relative_strength_and_defensive_cash(self):
        stock, f = self.fixture()
        result = market_context(stock, f)
        self.assertEqual(result["regime"], "falling")
        self.assertTrue(result["shadow_relative_strength"])
        self.assertFalse(result["shadow_defensive"])
        self.assertEqual(result["index_returns"]["KOSPI"], "-0.01")

    def test_missing_or_forming_index_is_unknown_not_zero(self):
        stock, f = self.fixture()
        f["market_observed_at"]["KOSPI"] = "2026-10-08T09:39:59+09:00"
        self.assertEqual(market_context(stock, f)["status"], "unavailable")
        self.assertIsNone(market_context(stock, {})["shadow_relative_strength"])

    def test_future_index_does_not_leak_into_aligned_return(self):
        stock, f = self.fixture()
        future = deepcopy(f["market_bars"]["KOSPI"][-1])
        future["timestamp"] = "2026-10-08T09:40:00+09:00"
        future.update(openPrice="200", closePrice="200", highPrice="200", lowPrice="200")
        f["market_bars"]["KOSPI"].append(future)
        self.assertEqual(market_context(stock, f)["index_returns"]["KOSPI"], "-0.01")

    def test_relative_loser_is_not_positive_signal(self):
        stock, f = self.fixture()
        stock[-1]["closePrice"] = "99.5"
        self.assertFalse(market_context(stock, f)["shadow_relative_strength"])

    def test_internal_gap_is_rejected(self):
        stock, f = self.fixture()
        del f["market_bars"]["KOSPI"][-5]
        self.assertEqual(market_context(stock, f)["status"], "unavailable")
