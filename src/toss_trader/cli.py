from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .api import TossApiError, TossClient
from .config import Settings
from .engine import TradingEngine
from .reconciliation import parse_account_snapshot


KST = timezone(timedelta(hours=9))
VERIFY_TERMINAL = {
    "FILLED",
    "CANCELED",
    "PARTIAL_CANCELED",
    "REJECTED",
    "REPLACED",
    "CANCEL_REJECTED",
    "REPLACE_REJECTED",
}


def _client(settings: Settings) -> TossClient:
    return TossClient(
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        account_seq=settings.account_seq,
    )


def _masked_account(account_no: str) -> str:
    if len(account_no) <= 4:
        return "*" * len(account_no)
    return "*" * (len(account_no) - 4) + account_no[-4:]


def command_check(settings: Settings) -> int:
    client = _client(settings)
    client.issue_token()
    accounts = client.accounts()
    calendar = client.kr_market_calendar()
    print("Toss OpenAPI 인증: 정상")
    print(f"거래 모드: {settings.mode}")
    print("계좌:")
    for account in accounts:
        print(
            f"  seq={account['accountSeq']} "
            f"type={account['accountType']} "
            f"no={_masked_account(str(account['accountNo']))}"
        )
    today = calendar.get("today", {})
    print(f"국내 시장 기준일: {today.get('date', 'unknown')}")
    if settings.account_seq is None and accounts:
        print(
            "\n.env에 다음 값을 추가하세요: "
            f"TOSS_ACCOUNT_SEQ={accounts[0]['accountSeq']}"
        )
    return 0


def command_scan(settings: Settings) -> int:
    engine = TradingEngine(settings, _client(settings))
    signals = engine.scan()
    if not signals:
        print("현재 조건을 통과한 종목이 없습니다.")
        return 0
    for signal in signals:
        print(
            f"{signal.symbol} score={signal.score:.4f} "
            f"price={signal.price} daily={signal.daily_change_rate:.2%} "
            f"m5={signal.momentum_5m:.2%} m15={signal.momentum_15m:.2%} "
            f"volume={signal.volume_surge:.2f}x "
            f"spread={signal.spread_rate:.2%}"
        )
    return 0


def command_status(settings: Settings) -> int:
    if not settings.state_path.exists():
        print("아직 생성된 매매 상태가 없습니다.")
        return 0
    print(settings.state_path.read_text(encoding="utf-8"))
    return 0


def _save_verify_journal(settings: Settings, value: dict | None) -> None:
    payload: dict = {}
    if settings.state_path.exists():
        payload = json.loads(settings.state_path.read_text(encoding="utf-8"))
    payload["pending_order"] = value
    settings.state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = settings.state_path.with_suffix(settings.state_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(settings.state_path)


def command_verify_live_order(settings: Settings, args: argparse.Namespace) -> int:
    if settings.mode != "live":
        raise ValueError("verify-live-order는 TRADING_MODE=live에서만 실행할 수 있습니다.")
    if not args.no_retry:
        raise ValueError("실주문 검증은 반드시 --no-retry를 지정해야 합니다.")
    expected_confirmation = f"LIVE-ORDER-{args.symbol}-{args.quantity}"
    if args.confirm != expected_confirmation:
        raise ValueError(f"확인 문자열이 일치하지 않습니다: {expected_confirmation}")
    if args.side != "BUY" or args.order_type != "LIMIT":
        raise ValueError("검증 주문은 BUY LIMIT만 허용합니다.")
    if args.quantity != 1:
        raise ValueError("검증 주문 수량은 정확히 1주만 허용합니다.")
    if args.price_source != "BEST_ASK":
        raise ValueError("검증 가격은 BEST_ASK만 허용합니다.")

    state_raw: dict = {}
    if settings.state_path.exists():
        state_raw = json.loads(settings.state_path.read_text(encoding="utf-8"))
        if state_raw.get("pending_order"):
            raise RuntimeError("로컬 pending journal이 있어 검증 주문을 중지합니다.")

    client = _client(settings)
    client.retry_enabled = False
    client.issue_token()
    accounts = client.accounts()
    if not any(int(item.get("accountSeq", -1)) == settings.account_seq for item in accounts):
        raise RuntimeError("설정된 계좌가 계좌 목록에 없습니다.")
    calendar = client.kr_market_calendar()
    today = calendar.get("today", {})
    now = datetime.now(KST)
    regular = (today.get("integrated") or {}).get("regularMarket") or {}
    if today.get("date") != now.date().isoformat() or not (
        regular.get("startTime") and regular.get("endTime")
    ):
        raise RuntimeError("현재 국내 정규장이 주문 가능한 상태가 아닙니다.")

    holdings = client.holdings()
    pending = client.pending_orders()
    buying_power = client.buying_power()
    snapshot = parse_account_snapshot(holdings, pending, buying_power)
    if snapshot.pending_orders:
        raise RuntimeError("계좌 전체에 기존 미체결 주문이 있어 검증 주문을 중지합니다.")
    existing = snapshot.positions.get(args.symbol)
    if existing is not None and existing.quantity > 0:
        raise RuntimeError("검증 종목을 이미 보유하고 있어 중복 매수를 중지합니다.")

    warnings = client.stock_warnings(args.symbol)
    if warnings:
        raise RuntimeError("검증 종목에 Toss 거래 제한/경고가 있어 주문을 중지합니다.")
    orderbook = client.orderbook(args.symbol)
    asks = orderbook.get("asks", [])
    if not asks:
        raise RuntimeError("최우선 매도호가가 없어 주문을 중지합니다.")
    price = Decimal(str(asks[0]["price"]))
    if price <= 0:
        raise RuntimeError("최우선 매도호가가 유효하지 않습니다.")
    limits = client.price_limits(args.symbol)
    lower = Decimal(str(limits.get("lowerLimitPrice", "0")))
    upper = Decimal(str(limits.get("upperLimitPrice", "0")))
    if (lower > 0 and price < lower) or (upper > 0 and price > upper):
        raise RuntimeError("최우선 매도호가가 상하한가 범위를 벗어났습니다.")
    cash = snapshot.cash
    expected_cost = price * args.quantity
    if expected_cost * Decimal("1.01") > cash:
        raise RuntimeError("수수료 여유를 포함한 매수가능금액이 부족합니다.")

    client_order_id = f"verify-{args.symbol}-{int(time.time())}-{uuid.uuid4().hex[:6]}"
    print(
        f"VERIFY_PRECHECK symbol={args.symbol} side=BUY quantity=1 "
        f"orderType=LIMIT price={price} expectedCost={expected_cost}"
    )
    _save_verify_journal(
        settings,
        {
            "symbol": args.symbol,
            "side": "BUY",
            "quantity": 1,
            "price": str(price),
            "reference_price": str(price),
            "client_order_id": client_order_id,
            "created_at": datetime.now(KST).isoformat(),
        },
    )
    try:
        created = client.create_order(
            symbol=args.symbol,
            side="BUY",
            quantity=1,
            client_order_id=client_order_id,
            order_type="LIMIT",
            price=price,
        )
    except TossApiError as exc:
        _save_verify_journal(settings, None)
        print(
            f"ORDER_REJECTED status={exc.status} code={exc.code} "
            f"message={exc} requestId={exc.request_id} data={exc.data}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        try:
            pending_after_error = client.pending_orders()
        except Exception:
            pending_after_error = []
        print(
            f"ORDER_STATUS_UNKNOWN error={type(exc).__name__} "
            f"clientOrderId={client_order_id} pendingCount={len(pending_after_error)}",
            file=sys.stderr,
        )
        return 1
    order_id = str(created["orderId"])
    journal = json.loads(settings.state_path.read_text(encoding="utf-8"))
    journal["pending_order"]["order_id"] = order_id
    temporary = settings.state_path.with_suffix(settings.state_path.suffix + ".tmp")
    temporary.write_text(json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(settings.state_path)
    print(f"ORDER_ACCEPTED orderId={order_id}")
    deadline = time.monotonic() + 30
    order: dict = {}
    try:
        while time.monotonic() < deadline:
            order = client.order(order_id)
            status = str(order.get("status", "UNKNOWN")).upper()
            if status in VERIFY_TERMINAL:
                break
            time.sleep(2)
    except Exception as exc:
        try:
            pending_after_error = client.pending_orders()
        except Exception:
            pending_after_error = []
        print(
            f"ORDER_STATUS_UNKNOWN orderId={order_id} "
            f"error={type(exc).__name__} pendingCount={len(pending_after_error)}",
            file=sys.stderr,
        )
        return 1
    status = str(order.get("status", "UNKNOWN")).upper()
    execution = order.get("execution") or {}
    filled = int(Decimal(str(execution.get("filledQuantity", "0"))))
    print(f"ORDER_STATUS orderId={order_id} status={status} filledQuantity={filled}")
    if status != "FILLED" or filled != 1:
        _save_verify_journal(settings, None)
        return 1
    after = parse_account_snapshot(
        client.holdings(), client.pending_orders(), client.buying_power()
    )
    recovered = after.positions.get(args.symbol)
    if recovered is None or recovered.quantity < 1:
        print("VERIFY_FAILED holding quantity did not reflect the filled order", file=sys.stderr)
        return 1
    _save_verify_journal(settings, None)
    print(
        f"VERIFY_SUCCEEDED symbol={args.symbol} quantity={recovered.quantity} "
        f"cash={after.cash} orderId={order_id}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toss-trader",
        description="Toss OpenAPI 단기 모멘텀 자동매매",
    )
    parser.add_argument(
        "command",
        choices=("check", "scan", "once", "run", "status", "verify-live-order"),
        help=(
            "check=인증 점검, scan=후보 조회, once=1회 실행, "
            "run=반복 실행, status=로컬 상태"
        ),
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help=".env와 state 디렉터리가 있는 프로젝트 루트",
    )
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--quantity", type=int, default=None)
    parser.add_argument("--side", choices=("BUY", "SELL"), default=None)
    parser.add_argument("--order-type", choices=("LIMIT", "MARKET"), default=None)
    parser.add_argument("--price-source", choices=("BEST_ASK",), default=None)
    parser.add_argument("--no-retry", action="store_true")
    parser.add_argument("--confirm", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        settings = Settings.from_project(args.project_root)
        if args.command == "check":
            return command_check(settings)
        if args.command == "scan":
            return command_scan(settings)
        if args.command == "status":
            return command_status(settings)
        if args.command == "verify-live-order":
            if args.symbol is None or args.quantity is None or args.side is None:
                raise ValueError("verify-live-order 필수 인자가 누락되었습니다.")
            return command_verify_live_order(settings, args)
        engine = TradingEngine(settings, _client(settings))
        if args.command == "once":
            engine.run_once()
            return 0
        engine.run_forever()
        return 0
    except KeyboardInterrupt:
        print("\n사용자 요청으로 종료했습니다.")
        return 130
    except (ValueError, TossApiError, RuntimeError) as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
