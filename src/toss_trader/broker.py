from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from .api import TossClient


@dataclass(frozen=True)
class Execution:
    order_id: str
    quantity: int
    price: Decimal


class PaperBroker:
    """Immediate-fill simulator with a small adverse slippage assumption."""

    def __init__(self, slippage_bps: Decimal = Decimal("5")) -> None:
        self.slippage = slippage_bps / Decimal("10000")

    def buy(
        self,
        symbol: str,
        quantity: int,
        reference_price: Decimal,
        *,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        price = reference_price * (Decimal("1") + self.slippage)
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        if on_submitted is not None:
            on_submitted(order_id)
        return Execution(order_id, quantity, price)

    def sell(
        self,
        symbol: str,
        quantity: int,
        reference_price: Decimal,
        *,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        price = reference_price * (Decimal("1") - self.slippage)
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        if on_submitted is not None:
            on_submitted(order_id)
        return Execution(order_id, quantity, price)


class LiveBroker:
    TERMINAL = {
        "FILLED",
        "CANCELED",
        "PARTIAL_CANCELED",
        "REJECTED",
        "REPLACED",
        "CANCEL_REJECTED",
        "REPLACE_REJECTED",
    }

    def __init__(self, client: TossClient) -> None:
        self.client = client

    def _execute(
        self,
        symbol: str,
        side: str,
        quantity: int,
        *,
        limit_price: Decimal | None = None,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        client_order_id = f"tat-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        created = self.client.create_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            client_order_id=client_order_id,
            order_type="LIMIT" if limit_price is not None else "MARKET",
            price=limit_price,
        )
        order_id = str(created["orderId"])
        if on_submitted is not None:
            on_submitted(order_id)
        deadline = time.monotonic() + 15
        order: dict = {}
        while time.monotonic() < deadline:
            order = self.client.order(order_id)
            if order.get("status") in self.TERMINAL:
                break
            time.sleep(1)
        if order.get("status") not in self.TERMINAL:
            self.client.cancel_order(order_id)
            time.sleep(1)
            order = self.client.order(order_id)
        execution = order.get("execution", {})
        filled_quantity = int(Decimal(str(execution.get("filledQuantity", "0"))))
        average_price = execution.get("averageFilledPrice")
        if filled_quantity <= 0 or average_price is None:
            raise RuntimeError(
                f"{side} 주문이 체결되지 않았습니다: "
                f"orderId={order_id}, status={order.get('status')}"
            )
        return Execution(order_id, filled_quantity, Decimal(str(average_price)))

    def buy(
        self,
        symbol: str,
        quantity: int,
        reference_price: Decimal,
        *,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        return self._execute(
            symbol,
            "BUY",
            quantity,
            limit_price=reference_price,
            on_submitted=on_submitted,
        )

    def sell(
        self,
        symbol: str,
        quantity: int,
        reference_price: Decimal,
        *,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        return self._execute(
            symbol,
            "SELL",
            quantity,
            on_submitted=on_submitted,
        )

