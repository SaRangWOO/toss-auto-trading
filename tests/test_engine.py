from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from toss_trader.config import LIVE_CONFIRMATION
from toss_trader.engine import KST, TradingEngine, _is_leveraged_or_inverse_etp
from toss_trader.state import PendingOrder, Position
from toss_trader.strategy import MomentumSignal

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


if __name__ == "__main__":
    unittest.main()
