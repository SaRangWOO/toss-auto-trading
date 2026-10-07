import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
import gzip
import json
from toss_trader.engine import KST
from toss_trader.experiment import MarketTape, ParallelPaper, metrics, replay, replay_sequence, safe_settings
from test_strategy import settings


class ExperimentTests(unittest.TestCase):
    def test_cache_and_replay_are_read_only(self):
        class Client:
            calls = 0
            def rankings(self, count):
                self.calls += 1
                return [{"symbol": "A"}]
        client = Client()
        tape = MarketTape(client)
        tape.rankings(10)[0]["symbol"] = "MUTATED"
        self.assertEqual(tape.rankings(10)[0]["symbol"], "A")
        self.assertEqual(client.calls, 1)
        self.assertEqual(MarketTape(records=tape.records).rankings(10)[0]["symbol"], "A")
        with self.assertRaises(RuntimeError):
            tape.create_order()
        with self.assertRaises(RuntimeError):
            MarketTape().rankings(10)

    def test_metrics_count_cost_adjusted_losses_and_drawdown(self):
        rows = [{"at": "2026-09-29", "equity": "100", "closed_pnl": None},
                {"at": "2026-09-29", "equity": "110", "closed_pnl": "10"},
                {"at": "2026-09-30", "equity": "90", "closed_pnl": "-20"}]
        result = metrics(rows)
        self.assertEqual(result["net_per_trade"], Decimal("-5"))
        self.assertEqual(result["max_marked_drawdown_krw"], Decimal("20"))
        self.assertEqual(result["net_without_best_one"], Decimal("-20"))

    def test_independent_portfolios_and_offline_cycle_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = settings(root)
            engine = ParallelPaper(config, object())
            now = datetime(2026, 9, 29, 8, 30, tzinfo=KST)
            engine.run_once(now)
            self.assertEqual(len({id(e.state) for e in engine.engines.values()}), 3)
            frame = next((root / "reports" / "parallel_paper_v2" / "tapes").rglob("*.gz"))
            replay(frame, root / "replayed")
            self.assertTrue((root / "replayed" / "retest" / "state" / "paper_portfolio.json").exists())
            for handler in list(engine.logger.handlers):
                handler.close()
                engine.logger.removeHandler(handler)

    def test_live_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                ParallelPaper(replace(settings(Path(folder)), mode="live"), object())

    def test_trial_deadline_replaced_and_completed_restart_still_runs_exits(self):
        class Client:
            def kr_market_calendar(self):
                return {"today": {"date": "2026-10-07", "integrated": {
                    "regularMarket": {"startTime": "09:00", "endTime": "15:30"}}}}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            engine = ParallelPaper(settings(root), Client())
            now = datetime(2026, 10, 7, 10, 0, tzinfo=KST)
            with patch("toss_trader.experiment.TradingEngine.run_once") as run:
                engine.run_once(now)
                self.assertEqual(run.call_count, 3)
                self.assertTrue(all(e.settings.entry_windows for e in engine.engines.values()))
            engine.progress["days"] = {str(i): {"completed": True} for i in range(5)}
            from toss_trader.experiment import write_json
            write_json(engine.progress_path, engine.progress)
            restarted = ParallelPaper(settings(root), Client())
            with patch("toss_trader.experiment.TradingEngine.run_once") as run:
                restarted.run_once(now)
                self.assertEqual(run.call_count, 3)  # Exit management is not skipped.
                self.assertTrue(all(not e.settings.entry_windows for e in restarted.engines.values()))
            for handler in list(engine.logger.handlers):
                handler.close()
                engine.logger.removeHandler(handler)

    def test_liquidity_rejection_precedes_candle_and_flow_fetch(self):
        from test_engine import FakeClient
        from toss_trader.engine import TradingEngine
        class Client(FakeClient):
            requested = []
            def rankings(self, count):
                return [{"symbol": symbol, "tradingAmount": amount,
                         "price": {"lastPrice": "100", "changeRate": "0.03"}}
                        for symbol, amount in [("LOW", "1"), ("HIGH", "60000000000")]]
            def stock_warnings(self, symbol):
                return []
            def candles(self, symbol, count):
                self.requested.append(symbol)
                return []
        with tempfile.TemporaryDirectory() as folder:
            config = replace(settings(Path(folder)), experiment_version=2, adaptive_shadow_enabled=False)
            client = Client()
            engine = TradingEngine(config, client)
            engine.scan(datetime(2026, 10, 2, 10, 10, tzinfo=KST))
            self.assertEqual(client.requested, ["HIGH"])
            for handler in list(engine.logger.handlers):
                handler.close()
                engine.logger.removeHandler(handler)

    def test_sequence_carries_cash_and_reports_swallowed_missing_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = settings(root)
            paths = []
            for minute in (0, 1):
                path = root / f"{minute}.json.gz"
                with gzip.open(path, "wt", encoding="utf-8") as stream:
                    json.dump({"at": f"2026-10-02T10:0{minute}:00+09:00", "records": {},
                        "variants": {v: {"settings": safe_settings(config)}
                                     for v in ("baseline", "continuation", "retest")}}, stream, default=str)
                paths.append(path)
            seen = []
            def cycle(engine, now):
                seen.append(engine.state.cash)
                engine.state.cash -= Decimal("10")
                try:
                    engine.client.prices(["missing"])
                except RuntimeError:
                    pass
            with patch("toss_trader.experiment.TradingEngine.run_once", cycle):
                result = replay_sequence(paths, root / "out")
            self.assertEqual(seen[:3], [Decimal("1000000")] * 3)
            self.assertEqual(seen[3:], [Decimal("999990")] * 3)
            self.assertFalse(result["performance_valid"])
            self.assertTrue(result["coverage"][0]["missing"])
            import logging
            logger = logging.getLogger("toss_trader")
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
