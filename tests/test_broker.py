from __future__ import annotations

import unittest
from decimal import Decimal

from toss_trader.broker import LiveBroker, OrderNotFilled


class FakeOrderClient:
    def __init__(self, order: dict) -> None:
        self.order_result = order
        self.created: dict | None = None
        self.canceled: list[str] = []

    def create_order(self, **kwargs: object) -> dict:
        self.created = kwargs
        return {"orderId": "server-order"}

    def order(self, order_id: str) -> dict:
        return self.order_result

    def cancel_order(self, order_id: str) -> dict:
        self.canceled.append(order_id)
        return {}


class LiveBrokerTests(unittest.TestCase):
    def test_partial_canceled_order_returns_actual_execution(self) -> None:
        client = FakeOrderClient(
            {
                "status": "PARTIAL_CANCELED",
                "execution": {
                    "filledQuantity": "2",
                    "averageFilledPrice": "85010",
                    "commission": "12",
                    "tax": "3",
                },
            }
        )
        submitted: list[str] = []
        execution = LiveBroker(client).buy(
            "005930",
            3,
            Decimal("85000"),
            client_order_id="client-order",
            on_submitted=submitted.append,
        )
        self.assertEqual(submitted, ["server-order"])
        self.assertEqual(execution.quantity, 2)
        self.assertEqual(execution.price, Decimal("85010"))
        self.assertEqual(execution.commission, Decimal("12"))
        self.assertEqual(execution.tax, Decimal("3"))
        assert client.created is not None
        self.assertEqual(client.created["limit_price"], Decimal("85000"))

    def test_canceled_unfilled_order_is_rejected(self) -> None:
        client = FakeOrderClient(
            {
                "status": "CANCELED",
                "execution": {"filledQuantity": "0"},
            }
        )
        with self.assertRaises(OrderNotFilled) as raised:
            LiveBroker(client).sell(
                "005930",
                2,
                Decimal("85000"),
                client_order_id="client-order",
            )
        self.assertEqual(raised.exception.order_id, "server-order")
        self.assertEqual(raised.exception.status, "CANCELED")


if __name__ == "__main__":
    unittest.main()
