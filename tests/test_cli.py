from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from toss_trader.cli import SingleInstanceLock


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


if __name__ == "__main__":
    unittest.main()
