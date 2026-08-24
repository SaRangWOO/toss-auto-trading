from __future__ import annotations

import gzip
import unittest
from decimal import Decimal

from toss_trader.api import TossClient


class RecordingClient(TossClient):
    def __init__(self) -> None:
        super().__init__("test-client", "test-secret", account_seq=1)
        self.request: dict | None = None

    def _request(
        self,
        method: str,
        path: str,
        group: str,
        *,
        query: dict | None = None,
        body: dict | None = None,
        account: bool = False,
    ) -> dict:
        self.request = {
            "method": method,
            "path": path,
            "group": group,
            "query": query,
            "body": body,
            "account": account,
        }
        return {"orderId": "order-test"}


class ApiTests(unittest.TestCase):
    def test_gzip_error_body_is_decoded(self) -> None:
        payload = (
            '{"error":{"code":"prerequisite-required",'
            '"message":"주문 전 필요한 사전 자격 요건이 충족되지 않았습니다."}}'
        ).encode("utf-8")
        decoded = TossClient._decode_body(gzip.compress(payload), "gzip")
        self.assertIn("prerequisite-required", decoded)
        self.assertIn("사전 자격", decoded)

    def test_gzip_magic_is_detected_without_header(self) -> None:
        payload = b'{"result":{"ok":true}}'
        self.assertEqual(
            TossClient._decode_body(gzip.compress(payload), None),
            payload.decode("utf-8"),
        )

    def test_limit_order_request_is_serialized_without_network(self) -> None:
        client = RecordingClient()
        result = client.create_order(
            symbol="005930",
            side="BUY",
            quantity=2,
            client_order_id="test-order-id",
            order_type="LIMIT",
            price=Decimal("85000"),
        )
        assert client.request is not None
        self.assertEqual(result["orderId"], "order-test")
        self.assertEqual(client.request["method"], "POST")
        self.assertEqual(client.request["path"], "/api/v1/orders")
        self.assertTrue(client.request["account"])
        self.assertEqual(
            client.request["body"],
            {
                "clientOrderId": "test-order-id",
                "symbol": "005930",
                "side": "BUY",
                "orderType": "LIMIT",
                "quantity": "2",
                "price": "85000",
            },
        )

    def test_limit_order_requires_positive_price(self) -> None:
        client = RecordingClient()
        with self.assertRaises(ValueError):
            client.create_order(
                symbol="005930",
                side="BUY",
                quantity=1,
                client_order_id="test-order-id",
                order_type="LIMIT",
            )

    def test_market_order_omits_price(self) -> None:
        client = RecordingClient()
        client.create_market_order(
            symbol="005930",
            side="SELL",
            quantity=2,
            client_order_id="test-order-id",
        )
        assert client.request is not None
        self.assertEqual(client.request["body"]["orderType"], "MARKET")
        self.assertNotIn("price", client.request["body"])

    def test_stocks_uses_stock_info_endpoint(self) -> None:
        client = RecordingClient()
        client._request = lambda method, path, group, **kwargs: [
            {"symbol": "069500", "securityType": "ETF", "leverageFactor": "1"}
        ]
        result = client.stocks(["069500"])
        self.assertEqual(result[0]["symbol"], "069500")

    def test_trades_uses_market_data_endpoint(self) -> None:
        client = RecordingClient()
        client._request = lambda method, path, group, **kwargs: {
            "trades": [{"price": "10000", "volume": "10"}]
        }
        result = client.trades("005930", count=50)
        self.assertEqual(result[0]["price"], "10000")


if __name__ == "__main__":
    unittest.main()
