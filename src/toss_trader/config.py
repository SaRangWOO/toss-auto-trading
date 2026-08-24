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
    paper_slippage_bps: Decimal
    paper_commission_rate: Decimal
    paper_sell_tax_rate: Decimal
    max_trade_krw: Decimal
    max_open_positions: int
    max_daily_entries: int
    max_daily_loss_rate: Decimal
    max_daily_loss_krw: Decimal
    max_daily_profit_lock_rate: Decimal
    risk_per_trade_rate: Decimal
    max_position_rate: Decimal
    stop_loss_rate: Decimal
    take_profit_rate: Decimal
    trailing_stop_rate: Decimal
    min_hold_seconds: int
    min_volatility_rate: Decimal
    max_stop_loss_rate: Decimal
    atr_stop_multiplier: Decimal
    atr_take_profit_multiplier: Decimal
    atr_trailing_multiplier: Decimal
    ranking_count: int
    candle_lookback_count: int
    adaptive_shadow_enabled: bool
    adaptive_shadow_max_candidates: int
    adaptive_shadow_min_score: Decimal
    breakout_confirmation_candles: int
    paper_continuation_entry_enabled: bool
    continuation_confirmation_evaluations: int
    continuation_breakout_max_age_minutes: int
    continuation_min_entry_score: Decimal
    continuation_min_volume_score: Decimal
    continuation_min_trade_pressure_score: Decimal
    continuation_min_orderbook_score: Decimal
    continuation_max_vwap_distance: Decimal
    continuation_max_breakout_distance: Decimal
    failure_exit_enabled: bool
    failure_exit_confirmation_candles: int
    failure_exit_max_trade_pressure: Decimal
    paper_position_review_enabled: bool
    paper_review_5m_seconds: int
    paper_review_10m_seconds: int
    paper_review_min_volume_ratio: Decimal
    paper_review_strong_volume_ratio: Decimal
    paper_review_max_weak_trade_pressure: Decimal
    paper_review_min_strong_trade_pressure: Decimal
    paper_review_min_10m_return: Decimal
    paper_profit_protection_enabled: bool
    paper_profit_activation_rate: Decimal
    paper_profit_max_giveback_fraction: Decimal
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
    institutional_proxy_filter: bool
    min_orderbook_imbalance_rate: Decimal
    min_institutional_proxy_score: int
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
                os.getenv("ENTRY_WINDOWS", "10:00-11:30,14:50-15:30")
            ),
            force_exit_time=os.getenv("FORCE_EXIT_TIME", "15:35").strip(),
            process_stop_time=os.getenv("PROCESS_STOP_TIME", "15:40").strip(),
            paper_starting_cash_krw=_decimal("PAPER_STARTING_CASH_KRW", "1000000"),
            paper_slippage_bps=_decimal("PAPER_SLIPPAGE_BPS", "5"),
            paper_commission_rate=_decimal("PAPER_COMMISSION_RATE", "0.00015"),
            paper_sell_tax_rate=_decimal("PAPER_SELL_TAX_RATE", "0.0015"),
            max_trade_krw=_decimal("MAX_TRADE_KRW", "100000"),
            max_open_positions=_integer("MAX_OPEN_POSITIONS", 2),
            max_daily_entries=_integer("MAX_DAILY_ENTRIES", 2),
            max_daily_loss_rate=_decimal("MAX_DAILY_LOSS_RATE", "0.010"),
            max_daily_loss_krw=_decimal("MAX_DAILY_LOSS_KRW", "0"),
            max_daily_profit_lock_rate=_decimal(
                "MAX_DAILY_PROFIT_LOCK_RATE", "0.020"
            ),
            risk_per_trade_rate=_decimal("RISK_PER_TRADE_RATE", "0.0035"),
            max_position_rate=_decimal("MAX_POSITION_RATE", "0.10"),
            stop_loss_rate=_decimal("STOP_LOSS_RATE", "0.008"),
            take_profit_rate=_decimal("TAKE_PROFIT_RATE", "0.015"),
            trailing_stop_rate=_decimal("TRAILING_STOP_RATE", "0.006"),
            min_hold_seconds=_integer("MIN_HOLD_SECONDS", 180),
            min_volatility_rate=_decimal("MIN_VOLATILITY_RATE", "0.004"),
            max_stop_loss_rate=_decimal("MAX_STOP_LOSS_RATE", "0.020"),
            atr_stop_multiplier=_decimal("ATR_STOP_MULTIPLIER", "1.5"),
            atr_take_profit_multiplier=_decimal(
                "ATR_TAKE_PROFIT_MULTIPLIER", "2.5"
            ),
            atr_trailing_multiplier=_decimal("ATR_TRAILING_MULTIPLIER", "1.25"),
            ranking_count=_integer("RANKING_COUNT", 30),
            candle_lookback_count=_integer("CANDLE_LOOKBACK_COUNT", 200),
            adaptive_shadow_enabled=_boolean("ADAPTIVE_SHADOW_ENABLED", True),
            adaptive_shadow_max_candidates=_integer(
                "ADAPTIVE_SHADOW_MAX_CANDIDATES", 10
            ),
            adaptive_shadow_min_score=_decimal(
                "ADAPTIVE_SHADOW_MIN_SCORE", "0.65"
            ),
            breakout_confirmation_candles=_integer(
                "BREAKOUT_CONFIRMATION_CANDLES", 2
            ),
            paper_continuation_entry_enabled=_boolean(
                "PAPER_CONTINUATION_ENTRY_ENABLED", True
            ),
            continuation_confirmation_evaluations=_integer(
                "CONTINUATION_CONFIRMATION_EVALUATIONS", 2
            ),
            continuation_breakout_max_age_minutes=_integer(
                "CONTINUATION_BREAKOUT_MAX_AGE_MINUTES", 10
            ),
            continuation_min_entry_score=_decimal(
                "CONTINUATION_MIN_ENTRY_SCORE", "0.85"
            ),
            continuation_min_volume_score=_decimal(
                "CONTINUATION_MIN_VOLUME_SCORE", "0.80"
            ),
            continuation_min_trade_pressure_score=_decimal(
                "CONTINUATION_MIN_TRADE_PRESSURE_SCORE", "0.55"
            ),
            continuation_min_orderbook_score=_decimal(
                "CONTINUATION_MIN_ORDERBOOK_SCORE", "0.50"
            ),
            continuation_max_vwap_distance=_decimal(
                "CONTINUATION_MAX_VWAP_DISTANCE", "0.05"
            ),
            continuation_max_breakout_distance=_decimal(
                "CONTINUATION_MAX_BREAKOUT_DISTANCE", "0.015"
            ),
            failure_exit_enabled=_boolean("FAILURE_EXIT_ENABLED", True),
            failure_exit_confirmation_candles=_integer(
                "FAILURE_EXIT_CONFIRMATION_CANDLES", 2
            ),
            failure_exit_max_trade_pressure=_decimal(
                "FAILURE_EXIT_MAX_TRADE_PRESSURE", "0.45"
            ),
            paper_position_review_enabled=_boolean(
                "PAPER_POSITION_REVIEW_ENABLED", True
            ),
            paper_review_5m_seconds=_integer("PAPER_REVIEW_5M_SECONDS", 300),
            paper_review_10m_seconds=_integer("PAPER_REVIEW_10M_SECONDS", 600),
            paper_review_min_volume_ratio=_decimal(
                "PAPER_REVIEW_MIN_VOLUME_RATIO", "0.60"
            ),
            paper_review_strong_volume_ratio=_decimal(
                "PAPER_REVIEW_STRONG_VOLUME_RATIO", "0.80"
            ),
            paper_review_max_weak_trade_pressure=_decimal(
                "PAPER_REVIEW_MAX_WEAK_TRADE_PRESSURE", "0.45"
            ),
            paper_review_min_strong_trade_pressure=_decimal(
                "PAPER_REVIEW_MIN_STRONG_TRADE_PRESSURE", "0.55"
            ),
            paper_review_min_10m_return=_decimal(
                "PAPER_REVIEW_MIN_10M_RETURN", "0.003"
            ),
            paper_profit_protection_enabled=_boolean(
                "PAPER_PROFIT_PROTECTION_ENABLED", True
            ),
            paper_profit_activation_rate=_decimal(
                "PAPER_PROFIT_ACTIVATION_RATE", "0.008"
            ),
            paper_profit_max_giveback_fraction=_decimal(
                "PAPER_PROFIT_MAX_GIVEBACK_FRACTION", "0.50"
            ),
            min_trading_amount_krw=_decimal(
                "MIN_TRADING_AMOUNT_KRW", "50000000000"
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
            institutional_proxy_filter=_boolean("INSTITUTIONAL_PROXY_FILTER", True),
            min_orderbook_imbalance_rate=_decimal(
                "MIN_ORDERBOOK_IMBALANCE_RATE", "0.10"
            ),
            min_institutional_proxy_score=_integer(
                "MIN_INSTITUTIONAL_PROXY_SCORE", 3
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
        if not 16 <= self.candle_lookback_count <= 200:
            raise ValueError("CANDLE_LOOKBACK_COUNT must be between 16 and 200")
        if not 1 <= self.adaptive_shadow_max_candidates <= 30:
            raise ValueError("ADAPTIVE_SHADOW_MAX_CANDIDATES must be between 1 and 30")
        if not Decimal("0") <= self.adaptive_shadow_min_score <= Decimal("1"):
            raise ValueError("ADAPTIVE_SHADOW_MIN_SCORE must be in [0, 1]")
        if not 1 <= self.breakout_confirmation_candles <= 3:
            raise ValueError("BREAKOUT_CONFIRMATION_CANDLES must be between 1 and 3")
        if not 2 <= self.continuation_confirmation_evaluations <= 3:
            raise ValueError(
                "CONTINUATION_CONFIRMATION_EVALUATIONS must be between 2 and 3"
            )
        if not 1 <= self.continuation_breakout_max_age_minutes <= 15:
            raise ValueError(
                "CONTINUATION_BREAKOUT_MAX_AGE_MINUTES must be between 1 and 15"
            )
        for name, value in (
            ("CONTINUATION_MIN_ENTRY_SCORE", self.continuation_min_entry_score),
            ("CONTINUATION_MIN_VOLUME_SCORE", self.continuation_min_volume_score),
            (
                "CONTINUATION_MIN_TRADE_PRESSURE_SCORE",
                self.continuation_min_trade_pressure_score,
            ),
            (
                "CONTINUATION_MIN_ORDERBOOK_SCORE",
                self.continuation_min_orderbook_score,
            ),
        ):
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError(f"{name} must be in [0, 1]")
        if not Decimal("0") < self.continuation_max_vwap_distance <= Decimal("0.10"):
            raise ValueError("CONTINUATION_MAX_VWAP_DISTANCE must be in (0, 0.10]")
        if not Decimal("0") < self.continuation_max_breakout_distance <= Decimal("0.05"):
            raise ValueError(
                "CONTINUATION_MAX_BREAKOUT_DISTANCE must be in (0, 0.05]"
            )
        if not 1 <= self.failure_exit_confirmation_candles <= 3:
            raise ValueError(
                "FAILURE_EXIT_CONFIRMATION_CANDLES must be between 1 and 3"
            )
        if not Decimal("0") <= self.failure_exit_max_trade_pressure <= Decimal("1"):
            raise ValueError("FAILURE_EXIT_MAX_TRADE_PRESSURE must be in [0, 1]")
        if not Decimal("0") <= self.paper_slippage_bps <= Decimal("50"):
            raise ValueError("PAPER_SLIPPAGE_BPS must be in [0, 50]")
        for name, value in (
            ("PAPER_COMMISSION_RATE", self.paper_commission_rate),
            ("PAPER_SELL_TAX_RATE", self.paper_sell_tax_rate),
        ):
            if not Decimal("0") <= value <= Decimal("0.01"):
                raise ValueError(f"{name} must be in [0, 0.01]")
        if not 120 <= self.paper_review_5m_seconds <= 900:
            raise ValueError("PAPER_REVIEW_5M_SECONDS must be between 120 and 900")
        if not self.paper_review_5m_seconds < self.paper_review_10m_seconds <= 1800:
            raise ValueError(
                "PAPER_REVIEW_10M_SECONDS must be above the 5m checkpoint and at most 1800"
            )
        for name, value in (
            ("PAPER_REVIEW_MAX_WEAK_TRADE_PRESSURE", self.paper_review_max_weak_trade_pressure),
            ("PAPER_REVIEW_MIN_STRONG_TRADE_PRESSURE", self.paper_review_min_strong_trade_pressure),
        ):
            if not Decimal("0") <= value <= Decimal("1"):
                raise ValueError(f"{name} must be in [0, 1]")
        if (
            self.paper_review_min_strong_trade_pressure
            <= self.paper_review_max_weak_trade_pressure
        ):
            raise ValueError(
                "PAPER_REVIEW_MIN_STRONG_TRADE_PRESSURE must exceed the weak threshold"
            )
        if not Decimal("0") < self.paper_review_min_volume_ratio <= Decimal("3"):
            raise ValueError("PAPER_REVIEW_MIN_VOLUME_RATIO must be in (0, 3]")
        if not (
            self.paper_review_min_volume_ratio
            <= self.paper_review_strong_volume_ratio
            <= Decimal("5")
        ):
            raise ValueError(
                "PAPER_REVIEW_STRONG_VOLUME_RATIO must be at least the minimum ratio and at most 5"
            )
        if not Decimal("0") <= self.paper_review_min_10m_return <= Decimal("0.03"):
            raise ValueError("PAPER_REVIEW_MIN_10M_RETURN must be in [0, 0.03]")
        if not Decimal("0") < self.paper_profit_activation_rate <= Decimal("0.05"):
            raise ValueError("PAPER_PROFIT_ACTIVATION_RATE must be in (0, 0.05]")
        if not Decimal("0.10") <= self.paper_profit_max_giveback_fraction <= Decimal("0.90"):
            raise ValueError(
                "PAPER_PROFIT_MAX_GIVEBACK_FRACTION must be in [0.10, 0.90]"
            )
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
        if self.min_hold_seconds < 0:
            raise ValueError("MIN_HOLD_SECONDS must be non-negative")
        if self.min_volatility_rate <= 0:
            raise ValueError("MIN_VOLATILITY_RATE must be positive")
        if self.max_stop_loss_rate < self.stop_loss_rate:
            raise ValueError("MAX_STOP_LOSS_RATE must not be below STOP_LOSS_RATE")
        if min(
            self.atr_stop_multiplier,
            self.atr_take_profit_multiplier,
            self.atr_trailing_multiplier,
        ) <= 0:
            raise ValueError("ATR multipliers must be positive")
        if self.max_daily_loss_krw < 0:
            raise ValueError("MAX_DAILY_LOSS_KRW must be non-negative")
        if not 5 <= self.order_timeout_seconds <= 60:
            raise ValueError("ORDER_TIMEOUT_SECONDS must be between 5 and 60")
        if not 1 <= self.max_consecutive_errors <= 10:
            raise ValueError("MAX_CONSECUTIVE_ERRORS must be between 1 and 10")
        if not 60 <= self.max_data_age_seconds <= 600:
            raise ValueError("MAX_DATA_AGE_SECONDS must be between 60 and 600")
        if not Decimal("0") < self.max_entry_slippage_rate <= Decimal("0.02"):
            raise ValueError("MAX_ENTRY_SLIPPAGE_RATE must be in (0, 0.02]")
        if not Decimal("0") <= self.min_orderbook_imbalance_rate < Decimal("1"):
            raise ValueError("MIN_ORDERBOOK_IMBALANCE_RATE must be in [0, 1)")
        if not 0 <= self.min_institutional_proxy_score <= 4:
            raise ValueError("MIN_INSTITUTIONAL_PROXY_SCORE must be between 0 and 4")
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
