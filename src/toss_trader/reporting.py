from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from .api import TossClient
from .config import Settings
from .state import PortfolioState


KST = timezone(timedelta(hours=9))
START_MARKER = "<!-- AUTO-TRADING:START -->"
END_MARKER = "<!-- AUTO-TRADING:END -->"


def _clock(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def _is_after_close(now: datetime, process_stop_time: str) -> bool:
    hour, minute = _clock(process_stop_time)
    current = now.astimezone(KST).time()
    return (current.hour, current.minute) >= (hour, minute)


def _decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def _money(value: Decimal | str | int) -> str:
    return f"{_decimal(value):,.0f} KRW"


def _short_order(order: dict[str, Any]) -> str:
    order_id = str(order.get("orderId", ""))
    return order_id[:10] + ("..." if len(order_id) > 10 else "") or "-"


def _execution(order: dict[str, Any]) -> dict[str, Any]:
    value = order.get("execution")
    return value if isinstance(value, dict) else {}


def _filled_quantity(order: dict[str, Any]) -> int:
    execution = _execution(order)
    value = execution.get("filledQuantity", order.get("filledQuantity", order.get("quantity", 0)))
    return int(_decimal(value))


def _filled_price(order: dict[str, Any]) -> Decimal:
    execution = _execution(order)
    return _decimal(
        execution.get(
            "averageFilledPrice",
            order.get("averageFilledPrice", order.get("price", 0)),
        )
    )


def _order_costs(order: dict[str, Any]) -> tuple[Decimal, Decimal]:
    execution = _execution(order)
    commission = _decimal(execution.get("commission", order.get("commission", 0)))
    tax = _decimal(execution.get("tax", order.get("tax", 0)))
    return commission, tax


def _order_timestamp(order: dict[str, Any]) -> str:
    return str(order.get("orderedAt") or order.get("createdAt") or "")


def _closed_trade_totals(orders: list[dict[str, Any]]) -> tuple[Decimal, Decimal, Decimal, int]:
    """Return price P&L, commissions, taxes and matched round-trip count."""
    lots: dict[str, list[list[Decimal | int]]] = {}
    gross = Decimal("0")
    commission = Decimal("0")
    tax = Decimal("0")
    matched = 0

    for order in sorted(orders, key=_order_timestamp):
        side = str(order.get("side", "")).upper()
        quantity = _filled_quantity(order)
        price = _filled_price(order)
        if quantity <= 0 or price <= 0:
            continue
        order_commission, order_tax = _order_costs(order)
        commission += order_commission
        tax += order_tax
        symbol = str(order.get("symbol", ""))
        if side == "BUY":
            lots.setdefault(symbol, []).append([quantity, price])
            continue
        if side != "SELL":
            continue
        remaining = quantity
        symbol_lots = lots.setdefault(symbol, [])
        while remaining and symbol_lots:
            lot_quantity, lot_price = symbol_lots[0]
            used = min(remaining, int(lot_quantity))
            gross += (price - lot_price) * used
            matched += 1
            remaining -= used
            lot_quantity = int(lot_quantity) - used
            if lot_quantity:
                symbol_lots[0][0] = lot_quantity
            else:
                symbol_lots.pop(0)
    return gross, commission, tax, matched


def _render_positions(state: PortfolioState) -> str:
    if not state.positions:
        return "- none"
    return "\n".join(
        f"- `{position.symbol}` qty={position.quantity}, entry={_money(position.entry_price)}, "
        f"opened={position.opened_at}"
        for position in state.positions.values()
    )


def _render_orders(orders: list[dict[str, Any]]) -> str:
    if not orders:
        return "- none"
    rows = [
        "| symbol | side | status | filled | avg price | commission | tax | order |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for order in orders:
        commission, tax = _order_costs(order)
        rows.append(
            f"| `{order.get('symbol', '-')}` | {order.get('side', '-')} | "
            f"{order.get('status', '-')} | {_filled_quantity(order)} | "
            f"{_money(_filled_price(order))} | {_money(commission)} | "
            f"{_money(tax)} | `{_short_order(order)}` |"
        )
    return "\n".join(rows)


def write_daily_report(
    settings: Settings,
    state: PortfolioState,
    client: TossClient | None = None,
    now: datetime | None = None,
) -> Path:
    now = now or datetime.now(KST)
    if not _is_after_close(now, settings.process_stop_time):
        raise RuntimeError(
            f"Daily report is available after market close ({settings.process_stop_time} KST)."
        )
    day = now.date().isoformat()
    cash = state.cash
    open_orders: list[dict[str, Any]] = []
    closed_orders: list[dict[str, Any]] = []
    api_error: str | None = None
    if settings.mode == "live" and client is not None:
        try:
            cash = _decimal(client.buying_power()["cashBuyingPower"])
            open_orders = client.list_orders("OPEN", date_from=day, date_to=day)
            closed_orders = client.list_orders("CLOSED", date_from=day, date_to=day)
        except Exception as exc:
            api_error = f"{type(exc).__name__}: {exc}"

    gross, commission, tax, matched = _closed_trade_totals(closed_orders)
    net_order_pnl = gross - commission - tax
    if not closed_orders or not matched:
        net_order_pnl = state.realized_pnl
    cash_delta = cash - state.initial_equity
    pending = "none"
    if state.pending_order:
        pending = (
            f"{state.pending_order.side} {state.pending_order.symbol} "
            f"qty={state.pending_order.quantity} order={state.pending_order.order_id or '-'}"
        )
    blocked = (
        "\n".join(f"- `{symbol}`: {reason}" for symbol, reason in state.blocked_symbols.items())
        or "- none"
    )
    block = f"""{START_MARKER}
## Daily Auto-Trading Report

- report schema: `2`
- updated: {now.isoformat(timespec="seconds")}
- mode: `{settings.mode}`
- process status: `running-or-scheduled`

### Result summary

| metric | value |
|---|---:|
| initial equity | {_money(state.initial_equity)} |
| current buying power | {_money(cash)} |
| net cash change | {_money(cash_delta)} |
| strategy realized P&L | {_money(state.realized_pnl)} |
| matched gross price P&L | {_money(gross)} |
| order commissions | {_money(commission)} |
| order taxes | {_money(tax)} |
| matched order net P&L | {_money(net_order_pnl)} |
| round trips matched | {matched} |

### Operations and risk

- daily entries: `{state.daily_entries}/{settings.max_daily_entries}`
- new entries halted: `{state.entries_halted}`
- halt reason: `{state.halt_reason or "none"}`
- consecutive errors: `{state.consecutive_errors}`
- last error: `{state.last_error or "none"}`
- pending journal: `{pending}`
- open orders from account: `{len(open_orders)}`

### Current positions

{_render_positions(state)}

### Today's closed orders

{_render_orders(closed_orders)}

### Blocked symbols

{blocked}

### Diagnostics

- report API query error: `{api_error or "none"}`
- `net cash change` includes account-level adjustments not attributable to matched order P&L.
- Secrets, access tokens and account identifiers are intentionally excluded.
{END_MARKER}
"""
    report_dir = settings.project_root / "report" / day[:4] / day[5:7]
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{day}.md"
    if path.exists():
        original = path.read_text(encoding="utf-8")
        if START_MARKER in original and END_MARKER in original:
            prefix = original.split(START_MARKER, 1)[0].rstrip()
            suffix = original.split(END_MARKER, 1)[1].lstrip()
            content = f"{prefix}\n\n{block}"
            if suffix:
                content += f"\n{suffix}"
        else:
            content = original.rstrip() + "\n\n" + block
    else:
        content = f"# {day} Auto-Trading Report\n\n{block}"
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
