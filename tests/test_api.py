from __future__ import annotations

import gzip
import unittest
from decimal import Decimal

from toss_trader.api import TossClient


class ApiTests(unittest.TestCase):
    def test_decode_body_handles_gzip_without_content_encoding(self) -> None:
        raw = gzip.compress(b'{"error": {"code": "price-out-of-range"}}')
        decoded = TossClient._decode_body(raw, None)
        self.assertIn("price-out-of-range", decoded)

    def test_limit_order_payload_contains_only_limit_price_fields(self) -> None:
        client = TossClient("id", "secret", account_seq=1)
        captured = {}

        def request(method, path, group, **kwargs):
            captured.update(kwargs)
            return {"orderId": "o1"}

        client._request = request  # type: ignore[method-assign]
        result = client.create_order(
            symbol="005930",
            side="BUY",
            quantity=1,
            client_order_id="cid",
            order_type="LIMIT",
            price=Decimal("70000"),
        )
        self.assertEqual(result["orderId"], "o1")
        self.assertEqual(captured["body"]["orderType"], "LIMIT")
        self.assertEqual(captured["body"]["price"], "70000")
        self.assertNotIn("confirmHighValueOrder", captured["body"])
        self.assertNotIn("timeInForce", captured["body"])

    def test_limit_order_requires_positive_price(self) -> None:
        client = TossClient("id", "secret", account_seq=1)
        with self.assertRaises(ValueError):
            client.create_order(
                symbol="005930",
                side="BUY",
                quantity=1,
                client_order_id="cid",
                order_type="LIMIT",
            )


if __name__ == "__main__":
    unittest.main()
