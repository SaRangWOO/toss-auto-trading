from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from toss_trader.research import (
    EventFlag,
    FlowSnapshot,
    MinuteBar,
    ResearchConfig,
    evaluate_research,
    write_research_report,
)


KST = timezone(timedelta(hours=9))


class ResearchTests(unittest.TestCase):
    def config(self) -> ResearchConfig:
        return ResearchConfig(
            min_trading_amount=Decimal("0"),
            min_daily_change=Decimal("-1"),
            max_daily_change=Decimal("1"),
            min_momentum_5m=Decimal("-1"),
            max_momentum_5m=Decimal("1"),
            min_momentum_15m=Decimal("-1"),
            max_momentum_15m=Decimal("1"),
            min_volume_surge=Decimal("1.5"),
            max_vwap_distance=Decimal("1"),
            breakout_confirmation_candles=2,
            continuation_max_age_minutes=10,
            stock_in_play_gap_rate=Decimal("0.02"),
            stock_in_play_opening_rvol=Decimal("2"),
            opening_volume_lookback_days=20,
            opening_volume_min_days=1,
            commission_rate=Decimal("0.00015"),
            sell_tax_rate=Decimal("0.0015"),
            slippage_bps=Decimal("5"),
        )

    def bars(self) -> list[MinuteBar]:
        bars = [
            MinuteBar(
                timestamp=datetime(2026, 8, 24, 9, 0, tzinfo=KST),
                symbol="005930",
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                volume=Decimal("100"),
            ),
            MinuteBar(
                timestamp=datetime(2026, 8, 24, 15, 30, tzinfo=KST),
                symbol="005930",
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                volume=Decimal("100"),
            ),
        ]
        start = datetime(2026, 8, 25, 9, 0, tzinfo=KST)
        for minute in range(101):
            timestamp = start + timedelta(minutes=minute)
            close = Decimal("102")
            high = Decimal("103")
            low = Decimal("101.5")
            volume = Decimal("100")
            if timestamp.time() == datetime(2026, 8, 25, 10, 0).time():
                close = Decimal("103.5")
                high = Decimal("104")
                low = Decimal("102.9")
                volume = Decimal("200")
            elif timestamp.time() == datetime(2026, 8, 25, 10, 1).time():
                close = Decimal("104")
                high = Decimal("104.2")
                low = Decimal("102.95")
                volume = Decimal("200")
            elif timestamp.time() >= datetime(2026, 8, 25, 10, 2).time():
                elapsed = Decimal(minute - 62)
                close = Decimal("104.5") + elapsed * Decimal("0.1")
                high = close + Decimal("0.2")
                low = close - Decimal("0.2")
                volume = Decimal("120")
            bars.append(
                MinuteBar(
                    timestamp=timestamp,
                    symbol="005930",
                    open=close if minute != 62 else Decimal("104.1"),
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
            )
        return bars

    def test_replay_uses_next_bar_and_compares_external_variants(self) -> None:
        flow = FlowSnapshot(
            timestamp=datetime(2026, 8, 25, 10, 1, tzinfo=KST),
            symbol="005930",
            institution_net_buy=Decimal("100"),
            foreign_net_buy=Decimal("50"),
            program_net_buy=Decimal("0"),
        )
        result = evaluate_research(
            self.bars(),
            self.config(),
            flows=[flow],
            split_date=date(2026, 8, 25),
        )
        self.assertEqual(
            {item.variant for item in result.trades},
            {
                "strict_ohlcv",
                "strict_stock_in_play",
                "retest_stock_in_play",
                "retest_flow_confirmed",
            },
        )
        strict = next(item for item in result.trades if item.variant == "strict_ohlcv")
        self.assertEqual(strict.signal_at.hour, 10)
        self.assertEqual(strict.signal_at.minute, 2)
        self.assertEqual(strict.entry_at.minute, 2)
        self.assertEqual(strict.entry_price, Decimal("104.1"))
        self.assertIsNotNone(strict.return_5m)
        assert strict.return_5m is not None
        raw_return = Decimal("105.0") / Decimal("104.1") - Decimal("1")
        self.assertEqual(
            strict.return_5m,
            raw_return - self.config().round_trip_cost_rate,
        )
        self.assertTrue(result.metadata["promotion_blocked"])

    def test_report_keeps_development_and_evaluation_separate(self) -> None:
        result = evaluate_research(
            self.bars(),
            self.config(),
            split_date=date(2026, 8, 25),
        )
        with tempfile.TemporaryDirectory() as temporary:
            markdown, details = write_research_report(result, Path(temporary))
            text = markdown.read_text(encoding="utf-8")
            self.assertIn("| evaluation | strict_ohlcv |", text)
            self.assertIn("Live promotion is blocked", text)
            self.assertTrue(details.exists())

    def test_future_news_event_is_not_used_by_morning_signal(self) -> None:
        config = replace(
            self.config(),
            stock_in_play_gap_rate=Decimal("1"),
            stock_in_play_opening_rvol=Decimal("100"),
        )
        future = EventFlag(
            timestamp=datetime(2026, 8, 25, 15, 0, tzinfo=KST),
            symbol="005930",
        )
        result = evaluate_research(self.bars(), config, events=[future])
        self.assertIn("strict_ohlcv", {item.variant for item in result.trades})
        self.assertNotIn(
            "strict_stock_in_play", {item.variant for item in result.trades}
        )
        known = EventFlag(
            timestamp=datetime(2026, 8, 25, 9, 45, tzinfo=KST),
            symbol="005930",
        )
        result = evaluate_research(self.bars(), config, events=[known])
        self.assertIn(
            "strict_stock_in_play", {item.variant for item in result.trades}
        )

    def test_previous_day_flow_does_not_confirm_today_retest(self) -> None:
        stale = FlowSnapshot(
            timestamp=datetime(2026, 8, 24, 15, 0, tzinfo=KST),
            symbol="005930",
            institution_net_buy=Decimal("1000"),
            foreign_net_buy=Decimal("1000"),
            program_net_buy=Decimal("1000"),
        )
        result = evaluate_research(self.bars(), self.config(), flows=[stale])
        self.assertNotIn(
            "retest_flow_confirmed", {item.variant for item in result.trades}
        )


if __name__ == "__main__":
    unittest.main()
