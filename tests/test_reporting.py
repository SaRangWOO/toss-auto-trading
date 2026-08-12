from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from toss_trader.reporting import _closed_trade_totals, write_daily_report
from toss_trader.state import PortfolioState


class ReportingTests(unittest.TestCase):
    def test_closed_trade_totals_match_fifo_and_costs(self) -> None:
        orders = [
            {
                "symbol": "000001",
                "side": "BUY",
                "status": "FILLED",
                "orderedAt": "2026-07-30T09:00:00+09:00",
                "execution": {
                    "filledQuantity": "2",
                    "averageFilledPrice": "1000",
                    "commission": "10",
                    "tax": "0",
                },
            },
            {
                "symbol": "000001",
                "side": "SELL",
                "status": "FILLED",
                "orderedAt": "2026-07-30T09:05:00+09:00",
                "execution": {
                    "filledQuantity": "2",
                    "averageFilledPrice": "1200",
                    "commission": "12",
                    "tax": "3",
                },
            },
        ]
        self.assertEqual(
            _closed_trade_totals(orders),
            (Decimal("400"), Decimal("22"), Decimal("3"), 1),
        )

    def test_report_contains_operational_and_pnl_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = PortfolioState.fresh("2026-07-30", Decimal("100000"))
            state.cash = Decimal("100385")
            state.realized_pnl = Decimal("400")
            state.daily_entries = 1
            settings = SimpleNamespace(
                mode="paper",
                project_root=root,
                max_daily_entries=10,
                process_stop_time="15:20",
            )
            path = write_daily_report(
                settings,
                state,
                now=datetime.fromisoformat("2026-07-30T15:20:00+09:00"),
            )
            self.assertEqual(path, root / "report" / "2026" / "07" / "2026-07-30.md")
            report = path.read_text(encoding="utf-8")
            self.assertIn("net cash change", report)
            self.assertIn("daily entries: `1/10`", report)
            self.assertIn("Today's closed orders", report)
            self.assertNotIn("TOSS_CLIENT_SECRET", report)

    def test_report_is_not_written_before_market_close(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = PortfolioState.fresh("2026-07-30", Decimal("100000"))
            settings = SimpleNamespace(
                mode="paper",
                project_root=root,
                max_daily_entries=10,
                process_stop_time="15:20",
            )
            with self.assertRaisesRegex(RuntimeError, "after market close"):
                write_daily_report(
                    settings,
                    state,
                    now=datetime.fromisoformat("2026-07-30T15:19:59+09:00"),
                )
            self.assertFalse((root / "report" / "2026" / "07" / "2026-07-30.md").exists())


if __name__ == "__main__":
    unittest.main()
