from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from toss_trader.config import Settings
from toss_trader.state import Position
from toss_trader.strategy import (
    analyze_candidate,
    adaptive_shadow_evaluate,
    exit_reason,
    average_true_range_rate,
    session_breakout_allowed,
    market_regime_allows,
    position_quantity,
)


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
        max_daily_loss_krw=Decimal("0"),
        max_daily_profit_lock_rate=Decimal("0.02"),
        risk_per_trade_rate=Decimal("0.0035"),
        max_position_rate=Decimal("0.10"),
        stop_loss_rate=Decimal("0.008"),
        take_profit_rate=Decimal("0.015"),
        trailing_stop_rate=Decimal("0.006"),
        min_hold_seconds=180,
        min_volatility_rate=Decimal("0.004"),
        max_stop_loss_rate=Decimal("0.020"),
        atr_stop_multiplier=Decimal("1.5"),
        atr_take_profit_multiplier=Decimal("2.5"),
        atr_trailing_multiplier=Decimal("1.25"),
        ranking_count=30,
        candle_lookback_count=200,
        adaptive_shadow_enabled=True,
        adaptive_shadow_max_candidates=10,
        adaptive_shadow_min_score=Decimal("0.65"),
        breakout_confirmation_candles=2,
        failure_exit_enabled=True,
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
        institutional_proxy_filter=True,
        min_orderbook_imbalance_rate=Decimal("0.10"),
        min_institutional_proxy_score=3,
        order_timeout_seconds=12,
        max_consecutive_errors=3,
        max_data_age_seconds=180,
        max_entry_slippage_rate=Decimal("0.003"),
        market_regime_filter=False,
        min_market_5m_rate=Decimal("-0.005"),
        min_market_15m_rate=Decimal("-0.010"),
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
                "bids": [{"price": "10580", "volume": "160"}],
            }
            signal = analyze_candidate(ranking, candles, orderbook, config)
            self.assertIsNotNone(signal)
            assert signal is not None
            self.assertEqual(signal.symbol, "005930")
            self.assertGreaterEqual(signal.volume_surge, Decimal("2"))
            self.assertEqual(signal.institutional_proxy_score, 4)

    def test_institutional_proxy_blocks_weak_orderbook(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                settings(Path(temporary)), min_institutional_proxy_score=4
            )
            candles = [
                {
                    "timestamp": f"2026-07-27T09:{index:02d}:00+09:00",
                    "closePrice": str(10000 + index * 20),
                    "volume": "2000" if index == 29 else "1000",
                }
                for index in range(30)
            ]
            ranking = {
                "symbol": "005930",
                "price": {"changeRate": "0.05"},
                "tradingAmount": "50000000000",
            }
            weak_orderbook = {
                "asks": [{"price": "10600", "volume": "150"}],
                "bids": [{"price": "10580", "volume": "100"}],
            }
            self.assertIsNone(
                analyze_candidate(ranking, candles, weak_orderbook, config)
            )

    def test_adaptive_shadow_returns_component_scores_without_live_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            candles = [
                {
                    "timestamp": f"2026-07-29T10:{index:02d}:00+09:00",
                    "highPrice": str(10000 + index * 20 + (500 if index == 29 else 0)),
                    "closePrice": str(10000 + index * 20 + (500 if index == 29 else 0)),
                    "volume": str(1000 + index * 10),
                }
                for index in range(30)
            ]
            evaluation = adaptive_shadow_evaluate(
                {"symbol": "005930", "tradingAmount": "50000000000"},
                candles,
                {
                    "asks": [{"price": "11000", "volume": "100"}],
                    "bids": [{"price": "10980", "volume": "250"}],
                },
                [{"price": "11000", "volume": "100"}],
                config,
                datetime.fromisoformat("2026-07-29T10:30:00+09:00"),
                True,
            )
            self.assertEqual(evaluation.symbol, "005930")
            self.assertGreaterEqual(evaluation.entry_score, Decimal("0"))
            self.assertIn("breakout_pct", evaluation.metrics)

    def test_position_size_respects_trade_cap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            quantity = position_quantity(
                cash=Decimal("1000000"),
                equity=Decimal("1000000"),
                price=Decimal("20000"),
                settings=settings(Path(temporary)),
            )
            self.assertEqual(quantity, 5)

    def test_position_size_can_use_authorized_two_hundred_thousand_won(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = replace(
                settings(Path(temporary)),
                max_trade_krw=Decimal("200000"),
                max_position_rate=Decimal("0.98"),
                risk_per_trade_rate=Decimal("0.01"),
            )
            config.validate()
            quantity = position_quantity(
                cash=Decimal("204644"),
                equity=Decimal("204644"),
                price=Decimal("10000"),
                settings=config,
            )
            self.assertEqual(quantity, 20)

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

    def test_minimum_hold_blocks_fast_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            position = Position(
                symbol="005930",
                quantity=1,
                entry_price=Decimal("10000"),
                high_water_price=Decimal("10000"),
                opened_at="2026-07-29T09:30:00+09:00",
            )
            self.assertIsNone(
                exit_reason(
                    position,
                    Decimal("9900"),
                    config,
                    now=datetime.fromisoformat("2026-07-29T09:32:00+09:00"),
                )
            )

    def test_breakout_failure_exits_below_entry_vwap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            position = Position(
                symbol="005930",
                quantity=1,
                entry_price=Decimal("10000"),
                high_water_price=Decimal("10000"),
                opened_at="2026-07-29T09:30:00+09:00",
                entry_vwap=Decimal("10050"),
                breakout_reference=Decimal("10000"),
            )
            self.assertEqual(
                exit_reason(
                    position,
                    Decimal("10020"),
                    config,
                    now=datetime.fromisoformat("2026-07-29T09:40:00+09:00"),
                    current_vwap=Decimal("10050"),
                    breakout_reference=Decimal("10000"),
                    failure_exit_enabled=True,
                ),
                "breakout_failure_vwap",
            )

    def test_atr_rate_uses_high_low_and_previous_close(self) -> None:
        candles = [
            {
                "timestamp": f"2026-07-29T09:{index:02d}:00+09:00",
                "highPrice": "110",
                "lowPrice": "90",
                "closePrice": "100",
            }
            for index in range(15)
        ]
        self.assertEqual(average_true_range_rate(candles, period=14), Decimal("0.2"))

    def test_session_breakout_requires_opening_range_break(self) -> None:
        candles = [
            {
                "timestamp": f"2026-07-29T09:{minute:02d}:00+09:00",
                "highPrice": "103",
                "closePrice": "102",
                "volume": "1000",
            }
            for minute in range(30)
        ]
        candles.append(
            {
                "timestamp": "2026-07-29T10:05:00+09:00",
                "highPrice": "105",
                "closePrice": "104",
                "volume": "2000",
            }
        )
        self.assertTrue(
            session_breakout_allowed(
                candles,
                datetime.fromisoformat("2026-07-29T10:06:00+09:00"),
                False,
            )
        )

    def test_market_regime_blocks_when_both_indices_sell_off(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            now = datetime(2026, 7, 29, 9, 50, tzinfo=timezone.utc)
            candles = []
            for index in range(20):
                candles.append(
                    {
                        "timestamp": (
                            datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)
                            .replace(minute=30 + index)
                            .isoformat()
                        ),
                        "closePrice": str(1000 - index * 2),
                        "volume": "1000",
                    }
                )
            self.assertFalse(
                market_regime_allows(
                    {"KOSPI": candles, "KOSDAQ": candles}, config, now
                )
            )


if __name__ == "__main__":
    unittest.main()
