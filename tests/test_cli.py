from __future__ import annotations

import unittest

from toss_trader.cli import build_parser


class CliTests(unittest.TestCase):
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
