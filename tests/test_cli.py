from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from toss_trader.cli import SingleInstanceLock, build_parser


class CliTests(unittest.TestCase):
    def test_second_instance_for_same_mode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "paper_trader.lock"
            with SingleInstanceLock(path):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with SingleInstanceLock(path):
                        pass

    def test_emergency_stop_script_targets_only_project_trader(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        script = (project_root / "scripts" / "stop.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("Stop-ScheduledTask", script)
        self.assertIn("Stop-Process", script)
        self.assertIn("toss_trader.cli run", script)
        self.assertIn("$normalizedRoot", script)

    def test_runner_persists_launcher_exit_diagnostics(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        script = (project_root / "scripts" / "run.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("launcher.log", script)
        self.assertIn("POWERSHELL_FATAL", script)
        self.assertIn("Out-File", script)
        self.assertIn("-Encoding utf8", script)
        self.assertIn("@Arguments", script)

    def test_scheduled_task_restarts_and_has_report_fallback(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        script = (project_root / "scripts" / "install-task.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("-RestartCount 3", script)
        self.assertIn("TossAutoTrading-DailyReport", script)
        self.assertIn("PROCESS_STOP_TIME", script)
        self.assertIn("$reportAt", script)

    def test_watchdog_script_checks_heartbeat_and_restarts_runner(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        script = (project_root / "scripts" / "watchdog.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("TRADING_MODE", script)
        self.assertIn('"${mode}_heartbeat.json"', script)
        self.assertIn("$processRunning", script)
        self.assertIn("Start-ScheduledTask", script)
        self.assertIn("120", script)

    def test_verify_live_order_arguments_are_available(self) -> None:
        args = build_parser().parse_args(
            [
                "verify-live-order",
                "--symbol",
                "090710",
                "--quantity",
                "1",
                "--side",
                "BUY",
                "--order-type",
                "LIMIT",
                "--price-source",
                "BEST_ASK",
                "--no-retry",
                "--confirm",
                "LIVE-ORDER-090710-1",
            ]
        )
        self.assertEqual(args.command, "verify-live-order")
        self.assertEqual(args.symbol, "090710")
        self.assertTrue(args.no_retry)


if __name__ == "__main__":
    unittest.main()
