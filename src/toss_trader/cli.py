from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO

from .api import TossApiError, TossClient
from .config import Settings
from .engine import TradingEngine, configure_logging
from .reconciliation import parse_account_snapshot
from .reporting import write_daily_report
from .state import PortfolioState


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


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError(
                "Another trading process is already running for this mode."
            ) from exc
        return self

    def __exit__(self, *args: object) -> None:
        if self.handle is None:
            return
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


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


def command_report(settings: Settings) -> int:
    engine = TradingEngine(settings, _client(settings))
    path = write_daily_report(settings, engine.state, engine.client)
    print(path)


def _research_symbols(value: str | None) -> list[str]:
    symbols = [item.strip() for item in (value or "").split(",") if item.strip()]
    if not symbols:
        raise ValueError("--symbols requires at least one stock code")
    invalid = [item for item in symbols if len(item) != 6 or not item.isalnum()]
    if invalid:
        raise ValueError("--symbols accepts comma-separated six-character stock codes")
    return list(dict.fromkeys(symbols))


def command_research_backtest(settings: Settings, args: argparse.Namespace) -> int:
    from .research import (
        ResearchConfig,
        evaluate_research,
        load_event_flags,
        load_flow_snapshots,
        load_minute_bars,
        write_research_report,
    )

    if args.candles is None:
        raise ValueError("research-backtest requires --candles")
    split_date = date.fromisoformat(args.split_date) if args.split_date else None
    bars = load_minute_bars(args.candles.resolve())
    flows = load_flow_snapshots(args.flows.resolve() if args.flows else None)
    events = load_event_flags(args.events.resolve() if args.events else None)
    result = evaluate_research(
        bars,
        ResearchConfig.from_settings(settings),
        flows=flows,
        events=events,
        split_date=split_date,
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else settings.project_root / "research_output"
    )
    markdown_path, json_path = write_research_report(result, output_dir)
    print(
        f"research replay complete bars={len(bars)} trades={len(result.trades)} "
        f"report={markdown_path} details={json_path}"
    )
    print("live promotion: blocked; results can nominate a paper experiment only")
    return 0


def command_research_fetch_kis(settings: Settings, args: argparse.Namespace) -> int:
    from .kis_data import (
        MINUTE_FIELDS,
        KisDataSettings,
        KisResearchClient,
        merge_csv_rows,
    )

    symbols = _research_symbols(args.symbols)
    if not args.start_date or not args.end_date:
        raise ValueError("research-fetch-kis requires --start-date and --end-date")
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if end < start:
        raise ValueError("--end-date must not be before --start-date")
    if (end - start).days > 366:
        raise ValueError("KIS historical minute requests are limited to a one-year range")
    today = datetime.now(KST).date()
    if end > today:
        raise ValueError("--end-date must not be in the future")
    if start < today - timedelta(days=366):
        raise ValueError("KIS retains at most about one year of historical minute data")
    data_settings = KisDataSettings.from_project(settings.project_root)
    client = KisResearchClient(data_settings)
    rows: list[dict[str, str]] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            for symbol in symbols:
                fetched = client.minute_bars(symbol, current)
                rows.extend(fetched)
                print(f"KIS minute data symbol={symbol} date={current} bars={len(fetched)}")
        current += timedelta(days=1)
    output = (
        args.output.resolve()
        if args.output
        else settings.project_root / "research_data" / "kis" / "minute_bars.csv"
    )
    added = merge_csv_rows(
        output,
        rows,
        fields=MINUTE_FIELDS,
        key_fields=("timestamp", "symbol"),
    )
    print(f"KIS read-only collection complete rows={len(rows)} added={added} output={output}")
    return 0


def command_research_fetch_flow(settings: Settings, args: argparse.Namespace) -> int:
    from .kis_data import (
        FLOW_FIELDS,
        KisDataSettings,
        KisResearchClient,
        merge_csv_rows,
        normalize_kis_flow_rows,
    )

    symbols = _research_symbols(args.symbols)
    data_settings = KisDataSettings.from_project(settings.project_root)
    client = KisResearchClient(data_settings)
    observed_at = datetime.now(KST)
    rows: list[dict[str, str]] = []
    for symbol in symbols:
        fetched = normalize_kis_flow_rows(
            symbol,
            client.investor_trend(symbol),
            observed_at,
        )
        rows.extend(fetched)
        print(f"KIS flow data symbol={symbol} snapshots={len(fetched)}")
    output = (
        args.output.resolve()
        if args.output
        else settings.project_root / "research_data" / "kis" / "flow_snapshots.csv"
    )
    added = merge_csv_rows(
        output,
        rows,
        fields=FLOW_FIELDS,
        key_fields=("timestamp", "symbol"),
    )
    print(f"KIS read-only flow collection complete rows={len(rows)} added={added} output={output}")
    return 0


def _save_verify_journal(
    settings: Settings,
    value: dict | None,
    *,
    starting_cash: Decimal | None = None,
) -> None:
    payload: dict = {}
    if not settings.state_path.exists():
        PortfolioState.fresh(
            datetime.now(KST).date().isoformat(),
            starting_cash or Decimal("0"),
        ).save(settings.state_path)
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
            "client_order_id": client_order_id,
            "created_at": datetime.now(KST).isoformat(),
        },
        starting_cash=snapshot.cash,
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
        choices=(
            "check",
            "scan",
            "once",
            "run",
            "status",
            "report",
            "verify-live-order",
            "research-backtest",
            "research-fetch-kis",
            "research-fetch-flow",
        ),
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
    parser.add_argument("--candles", type=Path, default=None)
    parser.add_argument("--flows", type=Path, default=None)
    parser.add_argument("--events", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--split-date", default=None)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--output", type=Path, default=None)
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
        if args.command == "report":
            return command_report(settings)
        if args.command == "research-backtest":
            return command_research_backtest(settings, args)
        if args.command == "research-fetch-kis":
            return command_research_fetch_kis(settings, args)
        if args.command == "research-fetch-flow":
            return command_research_fetch_flow(settings, args)
        if args.command == "verify-live-order":
            if args.symbol is None or args.quantity is None or args.side is None:
                raise ValueError("verify-live-order 필수 인자가 누락되었습니다.")
            return command_verify_live_order(settings, args)
        lock_path = (
            settings.project_root / "state" / f"{settings.mode}_trader.lock"
        )
        with SingleInstanceLock(lock_path):
            engine_type = TradingEngine
            if os.getenv("PAPER_PARALLEL_EXPERIMENT", "false").lower() == "true":
                from .experiment import ParallelPaper
                engine_type = ParallelPaper
            engine = engine_type(settings, _client(settings))
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
    except Exception as exc:
        # Scheduled Task only exposes the exit code. Keep unexpected failures
        # in the operational log before returning a non-zero code.
        try:
            logger = configure_logging(args.project_root)
            logger.exception("CLI_FATAL error=%s", exc)
        except Exception:
            pass
        print(f"Unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
