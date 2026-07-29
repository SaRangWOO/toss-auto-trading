from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .api import TossClient
from .config import Settings
from .state import PortfolioState


KST = timezone(timedelta(hours=9))
START_MARKER = "<!-- AUTO-TRADING:START -->"
END_MARKER = "<!-- AUTO-TRADING:END -->"


def _money(value: Decimal | str | int) -> str:
    return f"{Decimal(str(value)):,.0f}원"


def _short_order(order: dict) -> str:
    order_id = str(order.get("orderId", ""))
    return order_id[:10] + ("…" if len(order_id) > 10 else "")


def write_daily_report(
    settings: Settings,
    state: PortfolioState,
    client: TossClient | None = None,
    now: datetime | None = None,
) -> Path:
    now = now or datetime.now(KST)
    day = now.date().isoformat()
    cash = state.cash
    open_orders: list[dict] = []
    closed_orders: list[dict] = []
    api_error: str | None = None
    if settings.mode == "live" and client is not None:
        try:
            cash = Decimal(str(client.buying_power()["cashBuyingPower"]))
            open_orders = client.list_orders(
                "OPEN", date_from=day, date_to=day
            )
            closed_orders = client.list_orders(
                "CLOSED", date_from=day, date_to=day
            )
        except Exception as exc:
            api_error = f"{type(exc).__name__}: {exc}"

    positions = (
        "\n".join(
            f"- `{position.symbol}`: {position.quantity}주, "
            f"평균 {_money(position.entry_price)}"
            for position in state.positions.values()
        )
        or "- 없음"
    )
    blocked = (
        "\n".join(
            f"- `{symbol}`: {reason}"
            for symbol, reason in state.blocked_symbols.items()
        )
        or "- 없음"
    )
    orders = (
        "\n".join(
            f"- `{order.get('symbol')}` {order.get('side')} "
            f"{order.get('status')} / {_short_order(order)}"
            for order in closed_orders
        )
        or "- 없음"
    )
    pending = (
        f"{state.pending_order.side} {state.pending_order.symbol} "
        f"{state.pending_order.quantity}주"
        if state.pending_order
        else "없음"
    )
    block = f"""{START_MARKER}
## 자동 운용 결과

- 갱신: {now.isoformat(timespec="seconds")}
- 모드: `{settings.mode}`
- 매수 가능 금액: {_money(cash)}
- 시작 기준 금액: {_money(state.initial_equity)}
- 실현 손익: {_money(state.realized_pnl)}
- 신규 진입: {state.daily_entries}회
- 신규 진입 중지: {state.entries_halted}
- 중지 사유: `{state.halt_reason or "없음"}`
- 미해결 주문 저널: {pending}
- 실계좌 미체결 주문: {len(open_orders)}건
- 연속 시스템 오류: {state.consecutive_errors}회

### 봇 관리 포지션

{positions}

### 당일 종료 주문

{orders}

### 당일 제외 종목

{blocked}

### 진단

- 마지막 오류: `{state.last_error or "없음"}`
- 보고서 API 조회 오류: `{api_error or "없음"}`

> 이 보고서는 수익 보장이 아닌 운영·감사 기록입니다. `.env`, 토큰, Client
> Secret, 전체 계좌번호는 기록하지 않습니다.
{END_MARKER}
"""
    report_dir = settings.project_root / "report"
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
        content = f"# {day} 자동매매 보고서\n\n{block}"
    temporary = path.with_suffix(".md.tmp")
    temporary.write_text(content.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)
    return path
