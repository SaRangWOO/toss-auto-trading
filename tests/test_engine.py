from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from toss_trader.engine import KST, TradingEngine
from toss_trader.strategy import MomentumSignal

from test_strategy import settings


class FakeClient:
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
    )


class EngineTests(unittest.TestCase):
    def test_unaffordable_top_signal_does_not_block_next_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = settings(Path(temporary))
            engine = TradingEngine(config, FakeClient())
            engine.scan = lambda: [
                signal("EXPENSIVE", "200000", "10"),
                signal("AFFORDABLE", "20000", "9"),
            ]
            engine.run_once(datetime(2026, 7, 29, 9, 30, tzinfo=KST))
            self.assertNotIn("EXPENSIVE", engine.state.positions)
            self.assertIn("AFFORDABLE", engine.state.positions)
            self.assertEqual(engine.state.daily_entries, 1)
            for handler in list(engine.logger.handlers):
                handler.close()
                engine.logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
