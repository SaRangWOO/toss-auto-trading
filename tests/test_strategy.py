from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from toss_trader.config import Settings
from toss_trader.state import Position
from toss_trader.strategy import analyze_candidate, exit_reason, position_quantity


def settings(root: Path) -> Settings:
    return Settings(
        client_id="test",
        client_secret="test",
        account_seq=1,
        mode="paper",
        live_confirmation="",
        scan_interval_seconds=30,
        entry_windows=(("09:05", "10:30"), ("13:30", "14:45")),
        force_exit_time="15:10",
        process_stop_time="15:20",
        paper_starting_cash_krw=Decimal("1000000"),
        max_trade_krw=Decimal("100000"),
        max_open_positions=2,
        max_daily_entries=3,
        max_daily_loss_rate=Decimal("0.01"),
        max_daily_profit_lock_rate=Decimal("0.02"),
        risk_per_trade_rate=Decimal("0.0035"),
        max_position_rate=Decimal("0.10"),
        stop_loss_rate=Decimal("0.008"),
        take_profit_rate=Decimal("0.015"),
        trailing_stop_rate=Decimal("0.006"),
        ranking_count=30,
        min_trading_amount_krw=Decimal("10000000000"),
        min_daily_change_rate=Decimal("0.02"),
        max_daily_change_rate=Decimal("0.12"),
        min_5m_momentum_rate=Decimal("0.008"),
        max_5m_momentum_rate=Decimal("0.04"),
        min_15m_momentum_rate=Decimal("0.012"),
        max_15m_momentum_rate=Decimal("0.08"),
        min_volume_surge=Decimal("1.5"),
        max_spread_rate=Decimal("0.004"),
        max_price_over_vwap_rate=Decimal("0.05"),
        project_root=root,
    )


class StrategyTests(unittest.TestCase):
    def test_momentum_signal_passes_all_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            candles = []
            for index in range(30):
                price = 10000 + index * 20
                candles.append(
                    {
                        "timestamp": f"2026-07-27T09:{index:02d}:00+09:00",
                        "closePrice": str(price),
                        "volume": "2000" if index == 29 else "1000",
                    }
                )
            ranking = {
                "symbol": "005930",
                "price": {"changeRate": "0.05"},
                "tradingAmount": "50000000000",
            }
            orderbook = {
                "asks": [{"price": "10600", "volume": "100"}],
                "bids": [{"price": "10580", "volume": "100"}],
            }
            signal = analyze_candidate(ranking, candles, orderbook, config)
            self.assertIsNotNone(signal)
            assert signal is not None
            self.assertEqual(signal.symbol, "005930")
            self.assertGreaterEqual(signal.volume_surge, Decimal("2"))

    def test_position_size_respects_trade_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            quantity = position_quantity(
                cash=Decimal("1000000"),
                equity=Decimal("1000000"),
                price=Decimal("20000"),
                settings=settings(Path(temporary)),
            )
            self.assertEqual(quantity, 5)

    def test_previous_day_candles_are_not_used_for_opening_momentum(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            candles = []
            for index in range(20):
                candles.append(
                    {
                        "timestamp": f"2026-07-24T15:{index:02d}:00+09:00",
                        "closePrice": str(10000 + index * 20),
                        "volume": "1000",
                    }
                )
            for index in range(5):
                candles.append(
                    {
                        "timestamp": f"2026-07-27T09:0{index}:00+09:00",
                        "closePrice": str(10500 + index * 20),
                        "volume": "2000",
                    }
                )
            ranking = {
                "symbol": "005930",
                "price": {"changeRate": "0.05"},
                "tradingAmount": "50000000000",
            }
            orderbook = {
                "asks": [{"price": "10600", "volume": "100"}],
                "bids": [{"price": "10580", "volume": "100"}],
            }
            self.assertIsNone(
                analyze_candidate(ranking, candles, orderbook, config)
            )

    def test_hard_stop_and_take_profit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            position = Position(
                symbol="005930",
                quantity=10,
                entry_price=Decimal("10000"),
                high_water_price=Decimal("10000"),
                opened_at=datetime.now(timezone.utc).isoformat(),
            )
            self.assertEqual(
                exit_reason(position, Decimal("9920"), config), "hard_stop"
            )
            self.assertEqual(
                exit_reason(position, Decimal("10150"), config), "take_profit"
            )

    def test_trailing_stop_only_arms_after_gain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            position = Position(
                symbol="005930",
                quantity=10,
                entry_price=Decimal("10000"),
                high_water_price=Decimal("10100"),
                opened_at=datetime.now(timezone.utc).isoformat(),
            )
            self.assertEqual(
                exit_reason(position, Decimal("10039"), config), "trailing_stop"
            )


if __name__ == "__main__":
    unittest.main()
