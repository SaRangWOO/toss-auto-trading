from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from .state import Position, PortfolioState


class SyncStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True)
class AccountPosition:
    symbol: str
    quantity: int
    average_price: Decimal


@dataclass(frozen=True)
class PendingOrder:
    order_id: str
    symbol: str
    side: str
    quantity: int
    filled_quantity: int
    status: str


@dataclass(frozen=True)
class AccountSnapshot:
    positions: dict[str, AccountPosition]
    pending_orders: dict[str, PendingOrder]
    cash: Decimal


def _items(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _value(item: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return default


def parse_account_snapshot(
    holdings_payload: Any,
    pending_payload: Any,
    buying_power_payload: Any,
) -> AccountSnapshot:
    positions: dict[str, AccountPosition] = {}
    for item in _items(holdings_payload, ("holdings", "positions", "assets", "items")):
        symbol = str(_value(item, "symbol", "stockCode", "code", default=""))
        quantity = int(Decimal(str(_value(item, "quantity", "holdingQuantity", "availableQuantity", default="0"))))
        if not symbol or quantity <= 0:
            continue
        average = Decimal(str(_value(item, "averagePrice", "avgPrice", "entryPrice", "purchasePrice", default="0")))
        positions[symbol] = AccountPosition(symbol, quantity, average)

    pending: dict[str, PendingOrder] = {}
    for item in _items(pending_payload, ("orders", "pendingOrders", "openOrders", "items")):
        order_id = str(_value(item, "orderId", "id", "clientOrderId", default=""))
        if not order_id:
            continue
        pending[order_id] = PendingOrder(
            order_id=order_id,
            symbol=str(_value(item, "symbol", "stockCode", "code", default="")),
            side=str(_value(item, "side", "orderSide", default="")).upper(),
            quantity=int(Decimal(str(_value(item, "quantity", "orderedQuantity", default="0")))),
            filled_quantity=int(Decimal(str(_value(item, "filledQuantity", "executedQuantity", default="0")))),
            status=str(_value(item, "status", "orderStatus", default="UNKNOWN")).upper(),
        )
    cash = Decimal(str(_value(buying_power_payload, "cashBuyingPower", "buyingPower", "availableCash", default="0")))
    return AccountSnapshot(positions, pending, cash)


def reconcile_portfolio(
    state: PortfolioState,
    snapshot: AccountSnapshot,
    *,
    trading_day: str,
    now: datetime | None = None,
) -> list[str]:
    """Apply broker truth to local state and return auditable discrepancy reasons."""
    reasons: list[str] = []
    now = now or datetime.now(timezone.utc)
    state.sync_status = SyncStatus.IN_PROGRESS.value
    state.cash = snapshot.cash
    state.recovery_required = []

    for symbol in list(state.positions):
        local = state.positions[symbol]
        actual = snapshot.positions.get(symbol)
        if actual is None:
            reasons.append(f"local_only_position:{symbol}")
            del state.positions[symbol]
            continue
        if local.quantity != actual.quantity:
            reasons.append(f"quantity_mismatch:{symbol}:{local.quantity}->{actual.quantity}")
            local.quantity = actual.quantity
        if actual.average_price > 0 and local.entry_price != actual.average_price:
            reasons.append(f"average_price_mismatch:{symbol}")
            local.entry_price = actual.average_price
            local.high_water_price = max(local.high_water_price, actual.average_price)

    for symbol, actual in snapshot.positions.items():
        if symbol in state.positions:
            continue
        reasons.append(f"account_only_position:{symbol}")
        price = actual.average_price if actual.average_price > 0 else Decimal("0")
        state.positions[symbol] = Position(
            symbol=symbol,
            quantity=actual.quantity,
            entry_price=price,
            high_water_price=price,
            opened_at=now.isoformat(),
        )

    state.pending_orders = {
        order_id: {
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "filled_quantity": order.filled_quantity,
            "status": order.status,
        }
        for order_id, order in snapshot.pending_orders.items()
    }
    if state.pending_orders:
        reasons.append("pending_orders_present")
    state.recovery_required = list(reasons)
    state.trading_day = trading_day
    state.sync_status = SyncStatus.SUCCEEDED.value if not reasons else SyncStatus.DEGRADED.value
    state.sync_reason = ";".join(reasons) or None
    state.entries_halted = bool(reasons)
    state.halt_reason = "account_state_degraded" if reasons else state.halt_reason
    return reasons
