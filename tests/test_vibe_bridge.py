import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from decimal import Decimal as D

spec = importlib.util.spec_from_file_location("vibe_bridge", Path(__file__).resolve().parents[1]/"research/vibe_trading/bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


def trade(net="-1", day="2026-10-20"):
    return {"symbol": "0167A0", "quantity": 2, "entry": "100.05", "entry_cost": "200.13",
            "exit": "100", "net": net, "stress_net": "-2", "hold_seconds": 60,
            "opened_at": day+"T10:00:00+09:00", "exit_at": day+"T10:01:00+09:00",
            "reason": "structural_stop", "secret_sentinel": "DO_NOT_EXPORT"}


class VibeBridgeTests(unittest.TestCase):
    def test_fill_export_reconciles_costs_and_retains_exchange_suffix(self):
        rows = bridge.fills(trade(), "0167A0.KS", {"slippage_bps": "5"})
        buy, sell = rows
        pnl = (D(sell["price"])-D(buy["price"]))*2-D(buy["fee"])-D(sell["fee"])
        self.assertEqual(pnl, D("-1"))
        self.assertEqual(buy["symbol"], "0167A0.KS")
        self.assertGreaterEqual(D(sell["fee"]), 0)

    def test_statistics_removes_winners_and_counts_realized_drawdown(self):
        rows = [trade("10"), trade("-20"), trade("5")]
        r = bridge.statistics(rows)
        self.assertEqual(D(r["net_pnl_krw"]), -5)
        self.assertEqual(D(r["net_without_best_one_krw"]), -15)
        self.assertEqual(D(r["net_without_best_two_krw"]), -20)
        self.assertEqual(D(r["closed_trade_drawdown_krw"]), 20)

    def test_snapshot_excludes_future_trades_keeps_accounts_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/"source"
            source.mkdir()
            ledger = {"accounts": {"pullback/research": {"trades": [trade(), trade(day="2026-10-21")]},
                                   "pullback/execution": {"trades": [trade()]}}, "token": "DO_NOT_EXPORT"}
            (source/"ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
            (source/"manifest.json").write_text(json.dumps({"source_hash": "fixture", "policy": {"slippage_bps": "5"}}), encoding="utf-8")
            original = (source/"ledger.json").read_bytes()
            with patch.object(bridge, "load_markets", return_value={"0167A0": "KOSPI"}):
                result = bridge.export_bundle(source, "2026-10-20", root/"output")
            self.assertEqual(result["pullback/research"]["trades"], 1)
            self.assertEqual(result["pullback/execution"]["trades"], 1)
            self.assertEqual((source/"ledger.json").read_bytes(), original)
            for file in (root/"output").rglob("*"):
                if file.is_file():
                    self.assertNotIn("DO_NOT_EXPORT", file.read_text(encoding="utf-8"))
            with self.assertRaises(ValueError):
                bridge.export_bundle(source, "2026-10-20", root/"output")

    def test_invalid_cost_contract_is_rejected(self):
        with self.assertRaises(ValueError):
            bridge.fills(trade(net="100"), "0167A0.KS", {"slippage_bps": "5"})
