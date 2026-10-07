import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from test_strategy import settings
from toss_trader.entry_episode import evaluate_episode


class EpisodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = replace(settings(Path(self.temp.name)), experiment_variant="continuation_v2",
            continuation_min_entry_score=Decimal("0.78"),
            continuation_min_breakout_distance=Decimal("0.005"),
            continuation_max_breakout_distance=Decimal("0.02"))
        self.now = datetime.fromisoformat("2026-10-02T10:03:05+09:00")
        start = self.now.replace(hour=9, minute=0, second=0)
        self.bars = [{"timestamp": (start + timedelta(minutes=i)).isoformat(),
                      "closePrice": "99", "highPrice": "100", "lowPrice": "98", "volume": "100"}
                     for i in range(60)]
        for minute, close, high, low in [(0,"101","101.1","100.5"), (1,"100.2","100.4","100.1"), (2,"101.2","101.3","100.5")]:
            self.bars.append({"timestamp": start.replace(hour=10, minute=minute).isoformat(),
                              "closePrice":close,"highPrice":high,"lowPrice":low,"volume":"1000"})
        self.rank = {"symbol":"TEST", "tradingAmount":"60000000000"}

    def evaluate(self, bars=None, config=None, samples=None, now=None):
        now = now or self.now
        book = {"timestamp": now.isoformat(), "asks":[{"price":"101.3","volume":"100"}],
                "bids":[{"price":"101.2","volume":"1000"}]}
        trades = [{"timestamp":now.isoformat(),"price":"101.3","volume":"100"}]
        if samples is None:
            stamp = (now-timedelta(seconds=30)).isoformat()
            samples = [{"at":stamp,"quote_at":stamp,"pressure":"1","book":"0.8"}]
        return evaluate_episode(self.rank, bars or self.bars, book, trades,
                                config or self.config, now, samples)

    def test_frozen_reference_and_three_distinct_holds(self):
        evaluation, decision, _ = self.evaluate()
        self.assertTrue(decision.eligible, decision.rejection_reasons)
        self.assertEqual(decision.metrics["reference"], "100")
        self.assertEqual(decision.metrics["breakout_distance"], "0.012")
        self.assertEqual(decision.metrics["distinct_hold_bars"], "3")
        self.assertEqual(evaluation.breakout_score, Decimal("1"))

    def test_opening_extension_rejects_running_high_false_pass(self):
        bars = [dict(b) for b in self.bars]
        bars[-2].update(closePrice="112", highPrice="112.1")
        bars[-1].update(closePrice="113", highPrice="113.1")
        _, decision, _ = self.evaluate(bars=bars)
        self.assertIn("opening_extension_failed", decision.rejection_reasons)

    def test_same_candle_repeated_cannot_confirm(self):
        bars = self.bars[:-2]
        now = self.now.replace(minute=1)
        _, first, samples = self.evaluate(bars=bars, now=now)
        _, second, _ = self.evaluate(bars=bars, now=now+timedelta(seconds=20), samples=samples)
        self.assertIn("two_distinct_completed_bars_required", first.rejection_reasons)
        self.assertIn("two_distinct_completed_bars_required", second.rejection_reasons)

    def test_retest_independent_progression(self):
        config = replace(self.config, experiment_variant="retest_v2")
        _, decision, _ = self.evaluate(config=config)
        self.assertTrue(decision.eligible, decision.rejection_reasons)
        bars = [dict(b) for b in self.bars]
        bars[-2].update(lowPrice="100.5")
        _, decision, _ = self.evaluate(config=config, bars=bars)
        self.assertIn("retest_then_rebound_required", decision.rejection_reasons)

    def test_stale_samples_and_broken_episode(self):
        stamp = (self.now-timedelta(minutes=3)).isoformat()
        _, decision, _ = self.evaluate(samples=[{"at":stamp,"quote_at":stamp,"pressure":"1","book":"1"}])
        self.assertIn("flow_samples_insufficient", decision.rejection_reasons)
        bars = [dict(b) for b in self.bars]
        bars[-2]["closePrice"] = "99"
        _, decision, _ = self.evaluate(bars=bars)
        self.assertIn("two_distinct_completed_bars_required", decision.rejection_reasons)

    def test_future_and_duplicate_bars_do_not_add_hold(self):
        bars = self.bars[:-2] + [dict(self.bars[-3])]
        bars.append({**self.bars[-1], "timestamp": self.now.isoformat()})
        _, decision, _ = self.evaluate(bars=bars)
        self.assertEqual(decision.metrics["distinct_hold_bars"], "1")
