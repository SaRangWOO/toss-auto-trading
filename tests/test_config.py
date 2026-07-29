from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from toss_trader.config import LIVE_CONFIRMATION, Settings


class ConfigTests(unittest.TestCase):
    def test_default_configuration_is_paper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {}, clear=True):
                config = Settings.from_project(Path(temporary))
        self.assertEqual(config.mode, "paper")
        self.assertEqual(config.project_root, Path(temporary).resolve())

    def test_live_mode_requires_exact_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text(
                "\n".join(
                    (
                        "TOSS_CLIENT_ID=test-client",
                        "TOSS_CLIENT_SECRET=test-secret",
                        "TOSS_ACCOUNT_SEQ=1",
                        "TRADING_MODE=live",
                    )
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaisesRegex(ValueError, "실거래 잠금"):
                    Settings.from_project(root)

    def test_live_mode_accepts_pre_authorized_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".env").write_text(
                "\n".join(
                    (
                        "TOSS_CLIENT_ID=test-client",
                        "TOSS_CLIENT_SECRET=test-secret",
                        "TOSS_ACCOUNT_SEQ=1",
                        "TRADING_MODE=live",
                        f"LIVE_TRADING_CONFIRM={LIVE_CONFIRMATION}",
                    )
                ),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                config = Settings.from_project(root)
        self.assertEqual(config.mode, "live")
        self.assertEqual(config.live_confirmation, LIVE_CONFIRMATION)


if __name__ == "__main__":
    unittest.main()
