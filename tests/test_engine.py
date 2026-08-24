from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from toss_trader.config import LIVE_CONFIRMATION
from toss_trader.engine import KST, TradingEngine, _is_leveraged_or_inverse_etp
from toss_trader.state import PendingOrder, Position
from toss_trader.strategy import (
    AdaptiveShadowEvaluation,
    ContinuationEvaluation,
    MomentumSignal,
)

from test_strategy import settings


class FakeClient:
    def stocks(self, symbols: list[str]) -> list[dict]:
        return [
            {
                "symbol": symbol,
                "securityType": "STOCK",
                "leverageFactor": None,
            }
            for symbol in symbols
        ]

    def prices(self, symbols: list[str]) -> list[dict]:
        return []

    def kr_market_calendar(self) -> dict:
        return {
            "today": {
                "date": "2026-07-29",
                "integrated": {
                    "regularMarket": {
                        "startTime": "2026-07-29T09:00:00+09:00",
                        "endTime": "2026-07-29T15:30:00+09:00",
                    }
                },
            }
        }


class FakeLiveClient(FakeClient):
    def __init__(self) -> None:
        self.open_orders: list[dict] = []
        self.order_result: dict = {}
        self.canceled: list[str] = []

    def buying_power(self) -> dict:
        return {"cashBuyingPower": "204644"}

    def list_orders(self, status: str) -> list[dict]:
        return self.open_orders

    def order(self, order_id: str) -> dict:
        return self.order_result

    def cancel_order(self, order_id: str) -> dict:
        self.canceled.append(order_id)
        return {}


def signal(symbol: str, price: str, score: str) -> MomentumSignal:
    value = Decimal(price)
    return MomentumSignal(
        symbol=symbol,
        price=value,
        score=Decimal(score),
        daily_change_rate=Decimal("0.05"),
        momentum_5m=Decimal("0.01"),
        momentum_15m=Decimal("0.03"),
        volume_surge=Decimal("2"),
        vwap=value * Decimal("0.99"),
        spread_rate=Decimal("0.001"),
        institutional_proxy_score=3,
    )


class EngineTests(unittest.TestCase):
    def test_leveraged_and_inverse_etps_are_restricted(self) -> None:
        self.assertTrue(
            _is_leveraged_or_inverse_etp(
                {"securityType": "ETF", "leverageFactor": "2"}
            )
        )
        self.assertTrue(
            _is_leveraged_or_inverse_etp(
                {"securityType": "ETN", "leverageFactor": "-1"}
            )
        )
        self.assertFalse(
            _is_leveraged_or_inverse_etp(
                {"securityType": "ETF", "leverageFactor": "1"}
            )
        )

    def close_engine(self, engine: TradingEngine) -> None:
        for handler in list(engine.logger.handlers):
            handler.close()
            engine.logger.removeHandler(handler)

    @contextmanager
    def managed_engine(self, config, client):
        engine = TradingEngine(config, client)
        try:
            yield engine
        finally:
            self.close_engine(engine)

    def test_unaffordable_top_signal_does_not_block_next_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            with self.managed_engine(config, FakeClient()) as engine:
                engine.scan = lambda *args, **kwargs: [
                    signal("EXPENSIVE", "200000", "10"),
                    signal("AFFORDABLE", "20000", "9"),
                ]
                engine._fresh_entry_quote = lambda item, now: (item.price, 1000)
                engine.run_once(datetime(2026, 7, 29, 9, 30, tzinfo=KST))
                self.assertNotIn("EXPENSIVE", engine.state.positions)
                self.assertIn("AFFORDABLE", engine.state.positions)
                self.assertEqual(engine.state.daily_entries, 1)

    def test_live_initialization_uses_reported_buying_power(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                settings(Path(temporary)),
                mode="live",
                live_confirmation=LIVE_CONFIRMATION,
                account_seq=1,
            )
            config.validate()
            with self.managed_engine(config, FakeLiveClient()) as engine:
                self.assertEqual(engine.state.initial_equity, Decimal("204644"))
                self.assertEqual(engine.state.cash, Decimal("204644"))

    def test_account_open_order_prevents_duplicate_entry_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                settings(Path(temporary)),
                mode="live",
                live_confirmation=LIVE_CONFIRMATION,
                account_seq=1,
            )
            client = FakeLiveClient()
            client.open_orders = [{"orderId": "existing-order"}]
            with self.managed_engine(config, client) as engine:
                engine.scan = lambda *args, **kwargs: self.fail(
                    "scan must not run while an account order is open"
                )
                engine.run_once(datetime(2026, 7, 29, 9, 30, tzinfo=KST))
                self.assertEqual(engine.state.daily_entries, 0)

    def test_reconcile_partial_buy_applies_actual_fill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                settings(Path(temporary)),
                mode="live",
                live_confirmation=LIVE_CONFIRMATION,
                account_seq=1,
            )
            client = FakeLiveClient()
            client.order_result = {
                "status": "PARTIAL_CANCELED",
                "execution": {
                    "filledQuantity": "2",
                    "averageFilledPrice": "85010",
                    "commission": "12",
                    "tax": "0",
                },
            }
            with self.managed_engine(config, client) as engine:
                engine.state.pending_order = PendingOrder(
                    client_order_id="client-order",
                    symbol="005930",
                    side="BUY",
                    quantity=3,
                    created_at="2026-07-29T09:30:00+09:00",
                    reference_price=Decimal("85000"),
                    order_id="server-order",
                )
                engine._reconcile_pending(
                    datetime(2026, 7, 29, 9, 31, tzinfo=KST)
                )
                self.assertIsNone(engine.state.pending_order)
                self.assertEqual(engine.state.positions["005930"].quantity, 2)
                self.assertEqual(
                    engine.state.positions["005930"].entry_commission,
                    Decimal("12"),
                )
                self.assertEqual(engine.state.daily_entries, 1)

    def test_daily_loss_limit_halts_new_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.managed_engine(
                settings(Path(temporary)), FakeClient()
            ) as engine:
                engine.state.initial_equity = Decimal("1000000")
                pnl_rate = engine._daily_guard(Decimal("989999"), {})
                self.assertLess(pnl_rate, Decimal("-0.01"))
                self.assertTrue(engine.state.entries_halted)
                self.assertEqual(engine.state.halt_reason, "daily_loss_limit")

    def test_force_exit_closes_paper_position(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.managed_engine(
                settings(Path(temporary)), FakeClient()
            ) as engine:
                engine.state.positions["005930"] = Position(
                    symbol="005930",
                    quantity=2,
                    entry_price=Decimal("10000"),
                    high_water_price=Decimal("10000"),
                    opened_at="2026-07-29T09:30:00+09:00",
                )
                engine._manage_positions(
                    {"005930": Decimal("10010")},
                    datetime(2026, 7, 29, 15, 10, tzinfo=KST),
                )
                self.assertNotIn("005930", engine.state.positions)
                self.assertIsNone(engine.state.pending_order)

    def test_paper_position_review_marks_strong_trend(self) -> None:
        class ReviewClient(FakeClient):
            def candles(self, symbol: str, count: int) -> list[dict]:
                rows = []
                for index in range(20):
                    rows.append(
                        {
                            "timestamp": f"2026-07-29T09:{45 + index:02d}:00+09:00"
                            if index < 15
                            else f"2026-07-29T10:{index - 15:02d}:00+09:00",
                            "highPrice": "100.5",
                            "lowPrice": "99.5",
                            "closePrice": "100",
                            "volume": "200" if index >= 17 else "100",
                        }
                    )
                return rows

            def trades(self, symbol: str, count: int) -> list[dict]:
                return [{"price": "101", "volume": "100"}]

            def orderbook(self, symbol: str) -> dict:
                return {
                    "asks": [{"price": "101", "volume": "100"}],
                    "bids": [{"price": "100", "volume": "100"}],
                }

        with tempfile.TemporaryDirectory() as temporary:
            with self.managed_engine(
                settings(Path(temporary)), ReviewClient()
            ) as engine:
                engine.state.trading_day = "2026-07-29"
                engine.state.positions["005930"] = Position(
                    symbol="005930",
                    quantity=1,
                    entry_price=Decimal("100"),
                    high_water_price=Decimal("100"),
                    opened_at="2026-07-29T10:00:00+09:00",
                )
                engine._manage_positions(
                    {"005930": Decimal("101")},
                    datetime(2026, 7, 29, 10, 5, tzinfo=KST),
                )
                position = engine.state.positions["005930"]
                self.assertEqual(position.review_5m_outcome, "strong_trend")
                self.assertTrue(position.strong_trend_confirmed)
                review_path = (
                    Path(temporary)
                    / "reports"
                    / "position_reviews"
                    / "2026-07-29.jsonl"
                )
                record = json.loads(review_path.read_text(encoding="utf-8"))
                self.assertEqual(record["checkpoint"], "5m")
                self.assertEqual(record["outcome"], "strong_trend")

    def test_failure_exit_requires_two_distinct_completed_candles(self) -> None:
        class PositionClient(FakeClient):
            def __init__(self) -> None:
                self.latest_minute = 2

            def candles(self, symbol: str, count: int) -> list[dict]:
                rows = []
                for minute in range(45, 60):
                    rows.append(
                        {
                            "timestamp": f"2026-07-29T09:{minute:02d}:00+09:00",
                            "highPrice": "101",
                            "lowPrice": "100",
                            "closePrice": "101",
                            "volume": "100",
                        }
                    )
                for minute in range(self.latest_minute + 1):
                    rows.append(
                        {
                            "timestamp": f"2026-07-29T10:{minute:02d}:00+09:00",
                            "highPrice": "100",
                            "lowPrice": "99.5",
                            "closePrice": "99.5",
                            "volume": "100",
                        }
                    )
                return rows

            def trades(self, symbol: str, count: int) -> list[dict]:
                return [{"price": "99", "volume": "100"}]

            def orderbook(self, symbol: str) -> dict:
                return {
                    "asks": [{"price": "100", "volume": "100"}],
                    "bids": [{"price": "99", "volume": "100"}],
                }

        with tempfile.TemporaryDirectory() as temporary:
            client = PositionClient()
            config = replace(
                settings(Path(temporary)),
                paper_position_review_enabled=False,
            )
            with self.managed_engine(config, client) as engine:
                engine.state.trading_day = "2026-07-29"
                engine.state.positions["005930"] = Position(
                    symbol="005930",
                    quantity=1,
                    entry_price=Decimal("100"),
                    high_water_price=Decimal("100"),
                    opened_at="2026-07-29T09:55:00+09:00",
                    breakout_reference=Decimal("100"),
                )
                first = datetime(2026, 7, 29, 10, 3, tzinfo=KST)
                engine._manage_positions({"005930": Decimal("99.5")}, first)
                self.assertIn("005930", engine.state.positions)
                self.assertEqual(
                    engine.state.positions["005930"].failure_vwap_count, 1
                )
                engine._manage_positions({"005930": Decimal("99.5")}, first)
                self.assertEqual(
                    engine.state.positions["005930"].failure_vwap_count, 1
                )
                client.latest_minute = 3
                engine._manage_positions(
                    {"005930": Decimal("99.5")},
                    datetime(2026, 7, 29, 10, 4, tzinfo=KST),
                )
                self.assertNotIn("005930", engine.state.positions)

    def test_shadow_candidate_records_forward_outcome(self) -> None:
        class QuoteClient(FakeClient):
            def prices(self, symbols: list[str]) -> list[dict]:
                return [
                    {"symbol": symbol, "lastPrice": "101"}
                    for symbol in symbols
                ]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.managed_engine(settings(root), QuoteClient()) as engine:
                observed = datetime(2026, 7, 29, 10, 0, tzinfo=KST)
                evaluation = SimpleNamespace(
                    symbol="005930",
                    entry_score=Decimal("0.70"),
                    metrics={"reference_price": "100"},
                )
                engine._register_shadow_candidate(evaluation, observed)
                engine._update_shadow_tracking(
                    datetime(2026, 7, 29, 10, 30, tzinfo=KST)
                )
                item = engine._shadow_tracking[0]
                self.assertTrue(item["completed"])
                self.assertEqual(item["forward_returns"]["30m"], "0.01")
                self.assertEqual(item["mfe"], "0.01")
                self.assertTrue(
                    (root / "reports" / "shadow_tracking" / "2026-07-29.json").exists()
                )

    def test_continuation_requires_consecutive_evaluations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.managed_engine(
                settings(Path(temporary)), FakeClient()
            ) as engine:
                first = datetime(2026, 8, 20, 11, 5, 3, tzinfo=KST)
                count, confirmed = engine._update_continuation_confirmation(
                    "002990", True, first
                )
                self.assertEqual(count, 1)
                self.assertFalse(confirmed)
                count, confirmed = engine._update_continuation_confirmation(
                    "002990",
                    True,
                    datetime(2026, 8, 20, 11, 5, 33, tzinfo=KST),
                )
                self.assertEqual(count, 2)
                self.assertTrue(confirmed)
                count, confirmed = engine._update_continuation_confirmation(
                    "002990",
                    False,
                    datetime(2026, 8, 20, 11, 6, 3, tzinfo=KST),
                )
                self.assertEqual(count, 0)
                self.assertFalse(confirmed)

    def test_paper_scan_admits_confirmed_continuation_only_on_second_cycle(self) -> None:
        class ScanClient(FakeClient):
            def rankings(self, count: int) -> list[dict]:
                return [
                    {
                        "symbol": "002990",
                        "tradingAmount": "60000000000",
                        "price": {"lastPrice": "15160", "changeRate": "0.08"},
                    }
                ]

            def stock_warnings(self, symbol: str) -> list[dict]:
                return []

            def candles(self, symbol: str, count: int) -> list[dict]:
                return []

            def orderbook(self, symbol: str) -> dict:
                return {"asks": [], "bids": []}

            def trades(self, symbol: str, count: int) -> list[dict]:
                return []

        evaluation = AdaptiveShadowEvaluation(
            "002990",
            False,
            True,
            (),
            Decimal("0.93"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0.80"),
            Decimal("0.66"),
            Decimal("1"),
            Decimal("0.92"),
            {"reference_price": "15160"},
        )
        continuation = ContinuationEvaluation(True, (), {})
        expected_signal = signal("002990", "15160", "1")
        with tempfile.TemporaryDirectory() as temporary:
            with self.managed_engine(settings(Path(temporary)), ScanClient()) as engine:
                with (
                    patch("toss_trader.engine.adaptive_shadow_evaluate", return_value=evaluation),
                    patch("toss_trader.engine.continuation_entry_evaluate", return_value=continuation),
                    patch("toss_trader.engine.session_breakout_allowed", return_value=False),
                    patch("toss_trader.engine.analyze_candidate", return_value=expected_signal),
                ):
                    first = engine.scan(datetime(2026, 8, 20, 11, 5, 3, tzinfo=KST))
                    second = engine.scan(datetime(2026, 8, 20, 11, 5, 33, tzinfo=KST))
                self.assertEqual(first, [])
                self.assertEqual(second, [expected_signal])

    def test_live_scan_does_not_use_paper_continuation(self) -> None:
        class LiveScanClient(FakeLiveClient):
            def rankings(self, count: int) -> list[dict]:
                return [
                    {
                        "symbol": "002990",
                        "tradingAmount": "60000000000",
                        "price": {"lastPrice": "15160", "changeRate": "0.08"},
                    }
                ]

            def stock_warnings(self, symbol: str) -> list[dict]:
                return []

            def candles(self, symbol: str, count: int) -> list[dict]:
                return []

            def orderbook(self, symbol: str) -> dict:
                return {"asks": [], "bids": []}

            def trades(self, symbol: str, count: int) -> list[dict]:
                return []

        evaluation = AdaptiveShadowEvaluation(
            "002990",
            False,
            True,
            (),
            Decimal("0.93"),
            Decimal("1"),
            Decimal("1"),
            Decimal("0.80"),
            Decimal("0.66"),
            Decimal("1"),
            Decimal("0.92"),
            {"reference_price": "15160"},
        )
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                settings(Path(temporary)),
                mode="live",
                live_confirmation=LIVE_CONFIRMATION,
            )
            with self.managed_engine(config, LiveScanClient()) as engine:
                with (
                    patch("toss_trader.engine.adaptive_shadow_evaluate", return_value=evaluation),
                    patch("toss_trader.engine.continuation_entry_evaluate") as continuation_mock,
                    patch("toss_trader.engine.session_breakout_allowed", return_value=False),
                    patch("toss_trader.engine.analyze_candidate") as signal_mock,
                ):
                    result = engine.scan(
                        datetime(2026, 8, 20, 11, 5, 33, tzinfo=KST)
                    )
                self.assertEqual(result, [])
                continuation_mock.assert_not_called()
                signal_mock.assert_not_called()

    def test_shadow_record_contains_continuation_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.managed_engine(settings(root), FakeClient()) as engine:
                evaluation = AdaptiveShadowEvaluation(
                    "002990",
                    False,
                    False,
                    (),
                    Decimal("0.93"),
                    Decimal("1"),
                    Decimal("1"),
                    Decimal("0.80"),
                    Decimal("0.66"),
                    Decimal("1"),
                    Decimal("0.92"),
                    {"reference_price": "15160"},
                )
                continuation = ContinuationEvaluation(
                    True,
                    (),
                    {"breakout_age_minutes": "1.05"},
                )
                engine._record_adaptive_shadow(
                    evaluation,
                    datetime(2026, 8, 20, 11, 5, 33, tzinfo=KST),
                    continuation=continuation,
                    continuation_confirmation_count=2,
                    continuation_confirmed=True,
                )
                path = root / "reports" / "filter_funnel" / "2026-08-20.jsonl"
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(record["continuation"]["paper_only"])
                self.assertTrue(record["continuation"]["confirmed"])
                self.assertEqual(record["continuation"]["confirmation_count"], 2)


if __name__ == "__main__":
    unittest.main()
