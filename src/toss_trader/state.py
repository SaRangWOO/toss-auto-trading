from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any


@dataclass
class Position:
    symbol: str
    quantity: int
    entry_price: Decimal
    high_water_price: Decimal
    opened_at: str
    entry_commission: Decimal = Decimal("0")
    entry_tax: Decimal = Decimal("0")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Position":
        return cls(
            symbol=str(value["symbol"]),
            quantity=int(value["quantity"]),
            entry_price=Decimal(str(value["entry_price"])),
            high_water_price=Decimal(str(value["high_water_price"])),
            opened_at=str(value["opened_at"]),
            entry_commission=Decimal(str(value.get("entry_commission", "0"))),
            entry_tax=Decimal(str(value.get("entry_tax", "0"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "entry_price": str(self.entry_price),
            "high_water_price": str(self.high_water_price),
            "opened_at": self.opened_at,
            "entry_commission": str(self.entry_commission),
            "entry_tax": str(self.entry_tax),
        }


@dataclass
class PendingOrder:
    client_order_id: str
    symbol: str
    side: str
    quantity: int
    created_at: str
    reference_price: Decimal
    order_id: str | None = None
    reason: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PendingOrder":
        return cls(
            client_order_id=str(value["client_order_id"]),
            symbol=str(value["symbol"]),
            side=str(value["side"]),
            quantity=int(value["quantity"]),
            created_at=str(value["created_at"]),
            reference_price=Decimal(str(value["reference_price"])),
            order_id=value.get("order_id"),
            reason=value.get("reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "created_at": self.created_at,
            "reference_price": str(self.reference_price),
            "order_id": self.order_id,
            "reason": self.reason,
        }


@dataclass
class PortfolioState:
    trading_day: str
    initial_equity: Decimal
    cash: Decimal
    realized_pnl: Decimal = Decimal("0")
    positions: dict[str, Position] = field(default_factory=dict)
    daily_entries: int = 0
    entries_halted: bool = False
    halt_reason: str | None = None
    blocked_symbols: dict[str, str] = field(default_factory=dict)
    pending_order: PendingOrder | None = None
    consecutive_errors: int = 0
    last_error: str | None = None

    @classmethod
    def fresh(
        cls, trading_day: str, starting_cash: Decimal
    ) -> "PortfolioState":
        return cls(
            trading_day=trading_day,
            initial_equity=starting_cash,
            cash=starting_cash,
        )

    @classmethod
    def load_or_fresh(
        cls, path: Path, trading_day: str, starting_cash: Decimal
    ) -> "PortfolioState":
        if not path.exists():
            return cls.fresh(trading_day, starting_cash)
        raw = json.loads(path.read_text(encoding="utf-8"))
        state = cls(
            trading_day=str(raw["trading_day"]),
            initial_equity=Decimal(str(raw["initial_equity"])),
            cash=Decimal(str(raw["cash"])),
            realized_pnl=Decimal(str(raw.get("realized_pnl", "0"))),
            positions={
                symbol: Position.from_dict(position)
                for symbol, position in raw.get("positions", {}).items()
            },
            daily_entries=int(raw.get("daily_entries", 0)),
            entries_halted=bool(raw.get("entries_halted", False)),
            halt_reason=raw.get("halt_reason"),
            blocked_symbols={
                str(symbol): str(reason)
                for symbol, reason in raw.get("blocked_symbols", {}).items()
            },
            pending_order=(
                PendingOrder.from_dict(raw["pending_order"])
                if raw.get("pending_order")
                else None
            ),
            consecutive_errors=int(raw.get("consecutive_errors", 0)),
            last_error=raw.get("last_error"),
        )
        if state.trading_day != trading_day and not state.positions:
            return cls.fresh(trading_day, starting_cash)
        return state

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trading_day": self.trading_day,
            "initial_equity": str(self.initial_equity),
            "cash": str(self.cash),
            "realized_pnl": str(self.realized_pnl),
            "daily_entries": self.daily_entries,
            "entries_halted": self.entries_halted,
            "halt_reason": self.halt_reason,
            "blocked_symbols": self.blocked_symbols,
            "pending_order": (
                self.pending_order.to_dict() if self.pending_order else None
            ),
            "consecutive_errors": self.consecutive_errors,
            "last_error": self.last_error,
            "positions": {
                symbol: position.to_dict()
                for symbol, position in self.positions.items()
            },
        }
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def roll_to_new_day(self, trading_day: str, starting_equity: Decimal) -> None:
        if self.positions:
            raise RuntimeError("보유 포지션이 있는 동안 거래일을 변경할 수 없습니다.")
        self.trading_day = trading_day
        self.initial_equity = starting_equity
        self.realized_pnl = Decimal("0")
        self.daily_entries = 0
        self.entries_halted = False
        self.halt_reason = None
        self.blocked_symbols = {}
        self.pending_order = None
        self.consecutive_errors = 0
        self.last_error = None
