from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch
from decimal import Decimal
from pathlib import Path

from toss_trader.state import PendingOrder, PortfolioState


class StateTests(unittest.TestCase):
    def test_save_retries_transient_windows_replace_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "live_portfolio.json"
            state = PortfolioState.fresh("2026-08-04", Decimal("100000"))
            real_replace = os.replace
            attempts = 0

            def flaky_replace(source: str, target: str) -> None:
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise PermissionError("transient lock")
                real_replace(source, target)

            with patch("toss_trader.state.os.replace", side_effect=flaky_replace):
                state.save(path)
            self.assertEqual(attempts, 3)
            self.assertTrue(path.exists())

    def test_pending_order_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            state = PortfolioState.fresh("2026-07-29", Decimal("204644"))
            state.pending_order = PendingOrder(
                client_order_id="tat-260729-buy-abc",
                symbol="005930",
                side="BUY",
                quantity=2,
                created_at="2026-07-29T10:00:00+09:00",
                reference_price=Decimal("85000"),
                order_id="server-order-id",
            )
            state.save(path)
            restored = PortfolioState.load_or_fresh(
                path, "2026-07-29", Decimal("204644")
            )
            self.assertIsNotNone(restored.pending_order)
            assert restored.pending_order is not None
            self.assertEqual(restored.pending_order.order_id, "server-order-id")
            self.assertEqual(restored.pending_order.reference_price, Decimal("85000"))

    def test_new_day_uses_current_buying_power(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            PortfolioState.fresh(
                "2026-07-28", Decimal("190000")
            ).save(path)
            restored = PortfolioState.load_or_fresh(
                path, "2026-07-29", Decimal("204644")
            )
            self.assertEqual(restored.initial_equity, Decimal("204644"))
            self.assertEqual(restored.cash, Decimal("204644"))


if __name__ == "__main__":
    unittest.main()
