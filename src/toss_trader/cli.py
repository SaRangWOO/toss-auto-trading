from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import TossApiError, TossClient
from .config import Settings
from .engine import TradingEngine


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="toss-trader",
        description="Toss OpenAPI 단기 모멘텀 자동매매",
    )
    parser.add_argument(
        "command",
        choices=("check", "scan", "once", "run", "status"),
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
