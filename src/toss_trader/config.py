from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


LIVE_CONFIRMATION = "I_UNDERSTAND_REAL_MONEY"


def load_dotenv(path: Path) -> None:
    """Load a small, dependency-free .env file without overriding real env vars."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _decimal(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def _integer(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _windows(value: str) -> tuple[tuple[str, str], ...]:
    windows: list[tuple[str, str]] = []
    for item in value.split(","):
        start, separator, end = item.strip().partition("-")
        if not separator:
            raise ValueError(f"ENTRY_WINDOWS 항목 형식이 잘못되었습니다: {item!r}")
        windows.append((start, end))
    return tuple(windows)


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str
    account_seq: int | None
    mode: str
    live_confirmation: str
    scan_interval_seconds: int
    entry_windows: tuple[tuple[str, str], ...]
    force_exit_time: str
    process_stop_time: str
    paper_starting_cash_krw: Decimal
    max_trade_krw: Decimal
    max_open_positions: int
    max_daily_entries: int
    max_daily_loss_rate: Decimal
    max_daily_profit_lock_rate: Decimal
    risk_per_trade_rate: Decimal
    max_position_rate: Decimal
    stop_loss_rate: Decimal
    take_profit_rate: Decimal
    trailing_stop_rate: Decimal
    ranking_count: int
    min_trading_amount_krw: Decimal
    min_daily_change_rate: Decimal
    max_daily_change_rate: Decimal
    min_5m_momentum_rate: Decimal
    max_5m_momentum_rate: Decimal
    min_15m_momentum_rate: Decimal
    max_15m_momentum_rate: Decimal
    min_volume_surge: Decimal
    max_spread_rate: Decimal
    max_price_over_vwap_rate: Decimal
    order_timeout_seconds: int
    max_consecutive_errors: int
    max_data_age_seconds: int
    max_entry_slippage_rate: Decimal
    market_regime_filter: bool
    min_market_5m_rate: Decimal
    min_market_15m_rate: Decimal
    project_root: Path

    @classmethod
    def from_project(cls, project_root: Path | None = None) -> "Settings":
        root = (project_root or Path.cwd()).resolve()
        load_dotenv(root / ".env")
        account_text = os.getenv("TOSS_ACCOUNT_SEQ", "").strip()
        settings = cls(
            client_id=os.getenv("TOSS_CLIENT_ID", "").strip(),
            client_secret=os.getenv("TOSS_CLIENT_SECRET", "").strip(),
            account_seq=int(account_text) if account_text else None,
            mode=os.getenv("TRADING_MODE", "paper").strip().lower(),
            live_confirmation=os.getenv("LIVE_TRADING_CONFIRM", "").strip(),
            scan_interval_seconds=_integer("SCAN_INTERVAL_SECONDS", 30),
            entry_windows=_windows(
                os.getenv("ENTRY_WINDOWS", "09:05-10:30,13:30-14:45")
            ),
            force_exit_time=os.getenv("FORCE_EXIT_TIME", "15:10").strip(),
            process_stop_time=os.getenv("PROCESS_STOP_TIME", "15:20").strip(),
            paper_starting_cash_krw=_decimal("PAPER_STARTING_CASH_KRW", "1000000"),
            max_trade_krw=_decimal("MAX_TRADE_KRW", "100000"),
            max_open_positions=_integer("MAX_OPEN_POSITIONS", 2),
            max_daily_entries=_integer("MAX_DAILY_ENTRIES", 3),
            max_daily_loss_rate=_decimal("MAX_DAILY_LOSS_RATE", "0.010"),
            max_daily_profit_lock_rate=_decimal(
                "MAX_DAILY_PROFIT_LOCK_RATE", "0.020"
            ),
            risk_per_trade_rate=_decimal("RISK_PER_TRADE_RATE", "0.0035"),
            max_position_rate=_decimal("MAX_POSITION_RATE", "0.10"),
            stop_loss_rate=_decimal("STOP_LOSS_RATE", "0.008"),
            take_profit_rate=_decimal("TAKE_PROFIT_RATE", "0.015"),
            trailing_stop_rate=_decimal("TRAILING_STOP_RATE", "0.006"),
            ranking_count=_integer("RANKING_COUNT", 30),
            min_trading_amount_krw=_decimal(
                "MIN_TRADING_AMOUNT_KRW", "10000000000"
            ),
            min_daily_change_rate=_decimal("MIN_DAILY_CHANGE_RATE", "0.020"),
            max_daily_change_rate=_decimal("MAX_DAILY_CHANGE_RATE", "0.120"),
            min_5m_momentum_rate=_decimal("MIN_5M_MOMENTUM_RATE", "0.008"),
            max_5m_momentum_rate=_decimal("MAX_5M_MOMENTUM_RATE", "0.040"),
            min_15m_momentum_rate=_decimal("MIN_15M_MOMENTUM_RATE", "0.012"),
            max_15m_momentum_rate=_decimal("MAX_15M_MOMENTUM_RATE", "0.080"),
            min_volume_surge=_decimal("MIN_VOLUME_SURGE", "1.50"),
            max_spread_rate=_decimal("MAX_SPREAD_RATE", "0.004"),
            max_price_over_vwap_rate=_decimal(
                "MAX_PRICE_OVER_VWAP_RATE", "0.050"
            ),
            order_timeout_seconds=_integer("ORDER_TIMEOUT_SECONDS", 12),
            max_consecutive_errors=_integer("MAX_CONSECUTIVE_ERRORS", 3),
            max_data_age_seconds=_integer("MAX_DATA_AGE_SECONDS", 180),
            max_entry_slippage_rate=_decimal(
                "MAX_ENTRY_SLIPPAGE_RATE", "0.003"
            ),
            market_regime_filter=_boolean("MARKET_REGIME_FILTER", True),
            min_market_5m_rate=_decimal("MIN_MARKET_5M_RATE", "-0.005"),
            min_market_15m_rate=_decimal("MIN_MARKET_15M_RATE", "-0.010"),
            project_root=root,
        )
        settings.validate()
        return settings

    @property
    def state_path(self) -> Path:
        return self.project_root / "state" / f"{self.mode}_portfolio.json"

    def validate(self) -> None:
        if self.mode not in {"paper", "live"}:
            raise ValueError("TRADING_MODE는 paper 또는 live여야 합니다.")
        if self.scan_interval_seconds < 10:
            raise ValueError("SCAN_INTERVAL_SECONDS는 API 보호를 위해 10 이상이어야 합니다.")
        if not 1 <= self.max_open_positions <= 5:
            raise ValueError("MAX_OPEN_POSITIONS는 1~5 범위여야 합니다.")
        if not 1 <= self.max_daily_entries <= 20:
            raise ValueError("MAX_DAILY_ENTRIES는 1~20 범위여야 합니다.")
        for name, value, upper in (
            ("MAX_DAILY_LOSS_RATE", self.max_daily_loss_rate, Decimal("0.03")),
            ("RISK_PER_TRADE_RATE", self.risk_per_trade_rate, Decimal("0.01")),
            ("MAX_POSITION_RATE", self.max_position_rate, Decimal("1.00")),
            ("STOP_LOSS_RATE", self.stop_loss_rate, Decimal("0.03")),
        ):
            if value <= 0 or value > upper:
                raise ValueError(f"{name}은 0보다 크고 {upper} 이하여야 합니다.")
        if self.take_profit_rate <= self.stop_loss_rate:
            raise ValueError("TAKE_PROFIT_RATE는 STOP_LOSS_RATE보다 커야 합니다.")
        if self.process_stop_time <= self.force_exit_time:
            raise ValueError("PROCESS_STOP_TIME은 FORCE_EXIT_TIME보다 늦어야 합니다.")
        if not 5 <= self.order_timeout_seconds <= 60:
            raise ValueError("ORDER_TIMEOUT_SECONDS must be between 5 and 60")
        if not 1 <= self.max_consecutive_errors <= 10:
            raise ValueError("MAX_CONSECUTIVE_ERRORS must be between 1 and 10")
        if not 60 <= self.max_data_age_seconds <= 600:
            raise ValueError("MAX_DATA_AGE_SECONDS must be between 60 and 600")
        if not Decimal("0") < self.max_entry_slippage_rate <= Decimal("0.02"):
            raise ValueError("MAX_ENTRY_SLIPPAGE_RATE must be in (0, 0.02]")
        if self.mode == "live":
            missing = []
            if not self.client_id:
                missing.append("TOSS_CLIENT_ID")
            if not self.client_secret:
                missing.append("TOSS_CLIENT_SECRET")
            if self.account_seq is None:
                missing.append("TOSS_ACCOUNT_SEQ")
            if missing:
                raise ValueError("실거래 필수 설정 누락: " + ", ".join(missing))
            if self.live_confirmation != LIVE_CONFIRMATION:
                raise ValueError(
                    "실거래 잠금 상태입니다. 충분한 모의검증 후 "
                    f"LIVE_TRADING_CONFIRM={LIVE_CONFIRMATION} 를 직접 설정하세요."
                )
