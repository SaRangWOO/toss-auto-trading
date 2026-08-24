from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from .api import TossClient


@dataclass(frozen=True)
class Execution:
    order_id: str
    quantity: int
    price: Decimal
    commission: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")


class OrderNotFilled(RuntimeError):
    def __init__(self, order_id: str, status: str | None) -> None:
        super().__init__(
            f"Order was not filled: orderId={order_id}, status={status}"
        )
        self.order_id = order_id
        self.status = status


class PaperBroker:
    """Immediate-fill simulator with configurable adverse costs."""

    def __init__(
        self,
        slippage_bps: Decimal = Decimal("5"),
        commission_rate: Decimal = Decimal("0.00015"),
        sell_tax_rate: Decimal = Decimal("0.0015"),
    ) -> None:
        self.slippage = slippage_bps / Decimal("10000")
        self.commission_rate = commission_rate
        self.sell_tax_rate = sell_tax_rate

    @staticmethod
    def _won(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def buy(
        self,
        symbol: str,
        quantity: int,
        reference_price: Decimal,
        *,
        client_order_id: str | None = None,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        price = reference_price * (Decimal("1") + self.slippage)
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        if on_submitted is not None:
            on_submitted(order_id)
        commission = self._won(price * quantity * self.commission_rate)
        return Execution(order_id, quantity, price, commission, Decimal("0"))

    def sell(
        self,
        symbol: str,
        quantity: int,
        reference_price: Decimal,
        *,
        client_order_id: str | None = None,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        price = reference_price * (Decimal("1") - self.slippage)
        order_id = f"paper-{uuid.uuid4().hex[:12]}"
        if on_submitted is not None:
            on_submitted(order_id)
        gross = price * quantity
        commission = self._won(gross * self.commission_rate)
        tax = self._won(gross * self.sell_tax_rate)
        return Execution(order_id, quantity, price, commission, tax)


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

    def __init__(self, client: TossClient, timeout_seconds: int = 12) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds

    def _execute(
        self,
        symbol: str,
        side: str,
        quantity: int,
        *,
        client_order_id: str | None,
        limit_price: Decimal | None,
        on_submitted: Callable[[str], None] | None,
    ) -> Execution:
        client_order_id = (
            client_order_id
            or f"tat-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        )
        created = self.client.create_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            client_order_id=client_order_id,
            limit_price=limit_price,
        )
        order_id = str(created["orderId"])
        if on_submitted is not None:
            on_submitted(order_id)

        deadline = time.monotonic() + self.timeout_seconds
        order: dict = {}
        while time.monotonic() < deadline:
            order = self.client.order(order_id)
            if order.get("status") in self.TERMINAL:
                break
            time.sleep(1)

        if order.get("status") not in self.TERMINAL:
            self.client.cancel_order(order_id)
            cancel_deadline = time.monotonic() + 5
            while time.monotonic() < cancel_deadline:
                time.sleep(1)
                order = self.client.order(order_id)
                if (
                    order.get("status") in self.TERMINAL
                    or order.get("canceledAt")
                ):
                    break

        execution = order.get("execution", {})
        filled_quantity = int(Decimal(str(execution.get("filledQuantity", "0"))))
        average_price = execution.get("averageFilledPrice")
        if filled_quantity <= 0 or average_price is None:
            raise OrderNotFilled(order_id, order.get("status"))
        return Execution(
            order_id,
            filled_quantity,
            Decimal(str(average_price)),
            Decimal(str(execution.get("commission") or "0")),
            Decimal(str(execution.get("tax") or "0")),
        )

    def buy(
        self,
        symbol: str,
        quantity: int,
        reference_price: Decimal,
        *,
        client_order_id: str | None = None,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        # A marketable limit at the current best ask caps entry slippage.
        return self._execute(
            symbol,
            "BUY",
            quantity,
            client_order_id=client_order_id,
            limit_price=reference_price,
            on_submitted=on_submitted,
        )

    def sell(
        self,
        symbol: str,
        quantity: int,
        reference_price: Decimal,
        *,
        client_order_id: str | None = None,
        on_submitted: Callable[[str], None] | None = None,
    ) -> Execution:
        # Risk exits prioritize execution certainty.
        return self._execute(
            symbol,
            "SELL",
            quantity,
            client_order_id=client_order_id,
            limit_price=None,
            on_submitted=on_submitted,
        )
