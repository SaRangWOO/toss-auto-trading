from __future__ import annotations

import unittest
from datetime import datetime, timezone
from decimal import Decimal

from toss_trader.reconciliation import (
    SyncStatus,
    parse_account_snapshot,
    reconcile_portfolio,
)
from toss_trader.state import PortfolioState, Position


def position(symbol: str, quantity: int = 10, price: str = "10000") -> Position:
    value = Decimal(price)
    return Position(symbol, quantity, value, value, "2026-07-29T09:00:00+09:00")


def state(*positions: Position) -> PortfolioState:
    result = PortfolioState.fresh("2026-07-29", Decimal("1000000"))
    result.positions = {item.symbol: item for item in positions}
    return result


def snapshot(holdings=None, pending=None, cash="900000"):
    return parse_account_snapshot(
        {"holdings": holdings or []},
        {"orders": pending or []},
        {"cashBuyingPower": cash},
    )


class ReconciliationTests(unittest.TestCase):
    def test_account_only_position_is_recovered_and_degraded(self):
        current = state()
        reasons = reconcile_portfolio(current, snapshot([{"symbol": "005930", "quantity": "3", "averagePrice": "70000"}]), trading_day="2026-07-29")
        self.assertEqual(current.positions["005930"].quantity, 3)
        self.assertIn("account_only_position:005930", reasons)
        self.assertEqual(current.sync_status, SyncStatus.DEGRADED.value)

    def test_quantity_mismatch_uses_account_quantity(self):
        current = state(position("005930", 10))
        reconcile_portfolio(current, snapshot([{"symbol": "005930", "quantity": "4", "averagePrice": "10000"}]), trading_day="2026-07-29")
        self.assertEqual(current.positions["005930"].quantity, 4)

    def test_local_pending_without_account_pending_is_removed(self):
        current = state()
        current.pending_orders = {"old": {"symbol": "005930"}}
        reconcile_portfolio(current, snapshot(), trading_day="2026-07-29")
        self.assertEqual(current.pending_orders, {})
        self.assertEqual(current.sync_status, SyncStatus.SUCCEEDED.value)

    def test_account_pending_without_local_pending_blocks_entries(self):
        current = state()
        reconcile_portfolio(current, snapshot(pending=[{"orderId": "o1", "symbol": "005930", "side": "BUY", "quantity": "2", "status": "OPEN"}]), trading_day="2026-07-29")
        self.assertIn("o1", current.pending_orders)
        self.assertTrue(current.entries_halted)

    def test_partial_fill_is_preserved_as_pending(self):
        current = state()
        reconcile_portfolio(current, snapshot(pending=[{"orderId": "o1", "symbol": "005930", "quantity": "10", "filledQuantity": "3", "status": "PARTIALLY_FILLED"}]), trading_day="2026-07-29")
        self.assertEqual(current.pending_orders["o1"]["filled_quantity"], 3)

    def test_successful_order_with_no_local_state_recovers_holding(self):
        current = state()
        reconcile_portfolio(current, snapshot([{"symbol": "005930", "quantity": "3", "averagePrice": "10000"}]), trading_day="2026-07-29")
        self.assertEqual(current.positions["005930"].entry_price, Decimal("10000"))

    def test_local_state_is_not_treated_as_filled_when_account_is_empty(self):
        current = state(position("005930"))
        reasons = reconcile_portfolio(current, snapshot(), trading_day="2026-07-29")
        self.assertNotIn("005930", current.positions)
        self.assertIn("local_only_position:005930", reasons)

    def test_parse_api_failure_is_represented_by_failed_status_at_engine_boundary(self):
        self.assertEqual(parse_account_snapshot([], [], {"cashBuyingPower": "0"}).cash, Decimal("0"))

    def test_signal_during_degraded_sync_remains_blocked(self):
        current = state()
        reconcile_portfolio(current, snapshot(pending=[{"orderId": "o1", "status": "OPEN"}]), trading_day="2026-07-29")
        self.assertNotEqual(current.sync_status, SyncStatus.SUCCEEDED.value)

    def test_signal_after_clean_sync_is_allowed_by_status(self):
        current = state()
        reconcile_portfolio(current, snapshot(), trading_day="2026-07-29")
        self.assertEqual(current.sync_status, SyncStatus.SUCCEEDED.value)

    def test_duplicate_client_order_ids_collapse_to_one_pending_record(self):
        current = state()
        parsed = parse_account_snapshot([], {"orders": [{"clientOrderId": "dup", "status": "OPEN"}, {"clientOrderId": "dup", "status": "OPEN"}]}, {"cashBuyingPower": "1"})
        reconcile_portfolio(current, parsed, trading_day="2026-07-29")
        self.assertEqual(len(current.pending_orders), 1)

    def test_cash_priority_is_account_cash(self):
        current = state()
        reconcile_portfolio(current, snapshot(cash="123456"), trading_day="2026-07-29")
        self.assertEqual(current.cash, Decimal("123456"))

    def test_clean_sync_does_not_clear_a_strategy_risk_halt(self):
        current = state()
        current.entries_halted = True
        current.halt_reason = "daily_loss_limit"
        reconcile_portfolio(current, snapshot(), trading_day="2026-07-29")
        self.assertTrue(current.entries_halted)
        self.assertEqual(current.halt_reason, "daily_loss_limit")

    def test_recovered_position_has_a_crash_safe_timestamp(self):
        current = state()
        reconcile_portfolio(current, snapshot([{"symbol": "005930", "quantity": "1", "averagePrice": "10000"}]), trading_day="2026-07-29", now=datetime(2026, 7, 29, tzinfo=timezone.utc))
        self.assertTrue(current.positions["005930"].opened_at)


if __name__ == "__main__":
    unittest.main()
