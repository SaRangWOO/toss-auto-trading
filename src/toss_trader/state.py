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

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Position":
        return cls(
            symbol=str(value["symbol"]),
            quantity=int(value["quantity"]),
            entry_price=Decimal(str(value["entry_price"])),
            high_water_price=Decimal(str(value["high_water_price"])),
            opened_at=str(value["opened_at"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "entry_price": str(self.entry_price),
            "high_water_price": str(self.high_water_price),
            "opened_at": self.opened_at,
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
    sync_status: str = "NOT_STARTED"
    sync_reason: str | None = None
    pending_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    recovery_required: list[str] = field(default_factory=list)
    pending_order: dict[str, Any] | None = None
    blocked_symbols: dict[str, str] = field(default_factory=dict)
    last_error: str | None = None
    consecutive_errors: int = 0

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
            sync_status=str(raw.get("sync_status", "NOT_STARTED")),
            sync_reason=raw.get("sync_reason"),
            pending_orders=dict(raw.get("pending_orders", {})),
            recovery_required=[str(item) for item in raw.get("recovery_required", [])],
            pending_order=raw.get("pending_order"),
            blocked_symbols=dict(raw.get("blocked_symbols", {})),
            last_error=raw.get("last_error"),
            consecutive_errors=int(raw.get("consecutive_errors", 0)),
        )
        if state.trading_day != trading_day and not state.positions:
            return cls.fresh(trading_day, state.cash)
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
            "sync_status": self.sync_status,
            "sync_reason": self.sync_reason,
            "pending_orders": self.pending_orders,
            "recovery_required": self.recovery_required,
            "pending_order": self.pending_order,
            "blocked_symbols": self.blocked_symbols,
            "last_error": self.last_error,
            "consecutive_errors": self.consecutive_errors,
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
