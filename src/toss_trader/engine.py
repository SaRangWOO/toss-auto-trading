from __future__ import annotations

import logging
import time
from datetime import datetime, time as clock_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .api import TossClient
from .broker import LiveBroker, PaperBroker
from .config import Settings
from .state import PortfolioState, Position
from .strategy import MomentumSignal, analyze_candidate, exit_reason, position_quantity


KST = timezone(timedelta(hours=9))


def configure_logging(project_root: Path) -> logging.Logger:
    logger = logging.getLogger("toss_trader")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    log_dir = project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(
        log_dir / "trader.log", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def _parse_clock(value: str) -> clock_time:
    hour, minute = value.split(":", 1)
    return clock_time(int(hour), int(minute), tzinfo=KST)


class TradingEngine:
    def __init__(self, settings: Settings, client: TossClient) -> None:
        self.settings = settings
        self.client = client
        self.logger = configure_logging(settings.project_root)
        today = datetime.now(KST).date().isoformat()
        if settings.mode == "live" and not settings.state_path.exists():
            starting_cash = Decimal(str(client.buying_power()["cashBuyingPower"]))
        else:
            starting_cash = settings.paper_starting_cash_krw
        self.state = PortfolioState.load_or_fresh(
            settings.state_path, today, starting_cash
        )
        self.broker = (
            LiveBroker(client) if settings.mode == "live" else PaperBroker()
        )

    def _entry_window_open(self, now: datetime) -> bool:
        current = now.timetz()
        return any(
            _parse_clock(start) <= current <= _parse_clock(end)
            for start, end in self.settings.entry_windows
        )

    def _force_exit_due(self, now: datetime) -> bool:
        return now.timetz() >= _parse_clock(self.settings.force_exit_time)

    def _process_stop_due(self, now: datetime) -> bool:
        return now.timetz() >= _parse_clock(self.settings.process_stop_time)

    def _market_is_business_day(self, now: datetime) -> bool:
        calendar = self.client.kr_market_calendar()
        today = calendar.get("today", {})
        if today.get("date") != now.date().isoformat():
            return False
        integrated = today.get("integrated") or {}
        regular = integrated.get("regularMarket") or {}
        return bool(regular.get("startTime") and regular.get("endTime"))

    def _cash(self) -> Decimal:
        if self.settings.mode == "paper":
            return self.state.cash
        return Decimal(str(self.client.buying_power()["cashBuyingPower"]))

    def _prices_for_positions(self) -> dict[str, Decimal]:
        symbols = list(self.state.positions)
        if not symbols:
            return {}
        return {
            str(item["symbol"]): Decimal(str(item["lastPrice"]))
            for item in self.client.prices(symbols)
        }

    def _equity(
        self, cash: Decimal, prices: dict[str, Decimal]
    ) -> Decimal:
        position_value = sum(
            (
                prices.get(symbol, position.entry_price) * position.quantity
                for symbol, position in self.state.positions.items()
            ),
            Decimal("0"),
        )
        return cash + position_value

    def _sell(
        self, symbol: str, price: Decimal, reason: str, now: datetime
    ) -> None:
        position = self.state.positions[symbol]
        execution = self.broker.sell(
            symbol, position.quantity, reference_price=price
        )
        sold_quantity = min(execution.quantity, position.quantity)
        realized = (
            execution.price - position.entry_price
        ) * Decimal(sold_quantity)
        self.state.realized_pnl += realized
        if self.settings.mode == "paper":
            self.state.cash += execution.price * Decimal(sold_quantity)
        remaining = position.quantity - sold_quantity
        if remaining == 0:
            del self.state.positions[symbol]
        else:
            position.quantity = remaining
        self.logger.info(
            "EXIT mode=%s symbol=%s qty=%s price=%s pnl=%s reason=%s order=%s",
            self.settings.mode,
            symbol,
            sold_quantity,
            execution.price,
            realized,
            reason,
            execution.order_id,
        )
        self.state.save(self.settings.state_path)

    def _manage_positions(
        self, prices: dict[str, Decimal], now: datetime
    ) -> None:
        overnight = self.state.trading_day != now.date().isoformat()
        for symbol in list(self.state.positions):
            position = self.state.positions[symbol]
            current = prices.get(symbol)
            if current is None:
                self.logger.warning("현재가 누락으로 청산 판단 보류: %s", symbol)
                continue
            position.high_water_price = max(position.high_water_price, current)
            reason = exit_reason(position, current, self.settings)
            if overnight:
                reason = "overnight_recovery"
            elif self._force_exit_due(now):
                reason = "intraday_force_exit"
            if reason:
                self._sell(symbol, current, reason, now)

    def _daily_guard(
        self, cash: Decimal, prices: dict[str, Decimal]
    ) -> Decimal:
        equity = self._equity(cash, prices)
        if self.state.initial_equity <= 0:
            return Decimal("0")
        pnl_rate = equity / self.state.initial_equity - Decimal("1")
        if pnl_rate <= -self.settings.max_daily_loss_rate:
            self.state.entries_halted = True
            self.state.halt_reason = "daily_loss_limit"
        elif pnl_rate >= self.settings.max_daily_profit_lock_rate:
            self.state.entries_halted = True
            self.state.halt_reason = "daily_profit_lock"
        if self.state.entries_halted:
            self.logger.warning(
                "신규 진입 중지: reason=%s daily_pnl_rate=%.4f",
                self.state.halt_reason,
                pnl_rate,
            )
        return pnl_rate

    def scan(self) -> list[MomentumSignal]:
        signals: list[MomentumSignal] = []
        for ranking in self.client.rankings(self.settings.ranking_count):
            symbol = str(ranking["symbol"])
            if symbol in self.state.positions:
                continue
            # KR orders require whole shares. Avoid expensive candidates that
            # can never fit inside the configured per-trade ceiling.
            if Decimal(str(ranking["price"]["lastPrice"])) > self.settings.max_trade_krw:
                continue
            warnings = self.client.stock_warnings(symbol)
            if warnings:
                continue
            candles = self.client.candles(symbol, count=30)
            orderbook = self.client.orderbook(symbol)
            signal = analyze_candidate(
                ranking, candles, orderbook, self.settings
            )
            if signal is not None:
                signals.append(signal)
        return sorted(signals, key=lambda item: item.score, reverse=True)

    def _buy(
        self,
        signal: MomentumSignal,
        cash: Decimal,
        equity: Decimal,
        now: datetime,
    ) -> bool:
        quantity = position_quantity(
            cash=cash,
            equity=equity,
            price=signal.price,
            settings=self.settings,
        )
        if quantity <= 0:
            self.logger.info("예산 부족으로 진입 생략: %s", signal.symbol)
            return False
        execution = self.broker.buy(
            signal.symbol, quantity, reference_price=signal.price
        )
        cost = execution.price * Decimal(execution.quantity)
        if self.settings.mode == "paper":
            if cost > self.state.cash:
                self.logger.warning("모의계좌 현금 부족으로 진입 취소: %s", signal.symbol)
                return False
            self.state.cash -= cost
        self.state.positions[signal.symbol] = Position(
            symbol=signal.symbol,
            quantity=execution.quantity,
            entry_price=execution.price,
            high_water_price=execution.price,
            opened_at=now.isoformat(),
        )
        self.state.daily_entries += 1
        self.logger.info(
            "ENTRY mode=%s symbol=%s qty=%s price=%s score=%.4f "
            "m5=%.4f m15=%.4f volume=%.2f spread=%.4f order=%s",
            self.settings.mode,
            signal.symbol,
            execution.quantity,
            execution.price,
            signal.score,
            signal.momentum_5m,
            signal.momentum_15m,
            signal.volume_surge,
            signal.spread_rate,
            execution.order_id,
        )
        self.state.save(self.settings.state_path)
        return True

    def run_once(self, now: datetime | None = None) -> None:
        now = now or datetime.now(KST)
        self.logger.info(
            "CYCLE mode=%s time=%s positions=%s",
            self.settings.mode,
            now.isoformat(timespec="seconds"),
            len(self.state.positions),
        )
        prices = self._prices_for_positions()
        self._manage_positions(prices, now)
        prices = self._prices_for_positions()
        cash = self._cash()
        if self.settings.mode == "live":
            self.state.cash = cash
        if (
            self.state.trading_day != now.date().isoformat()
            and not self.state.positions
        ):
            self.state.roll_to_new_day(now.date().isoformat(), cash)
        self._daily_guard(cash, prices)

        if self.state.entries_halted:
            for symbol in list(self.state.positions):
                price = prices.get(symbol)
                if price is not None:
                    self._sell(
                        symbol,
                        price,
                        self.state.halt_reason or "daily_guard",
                        now,
                    )
            self.state.save(self.settings.state_path)
            return
        if (
            self._force_exit_due(now)
            or not self._entry_window_open(now)
            or not self._market_is_business_day(now)
        ):
            self.state.save(self.settings.state_path)
            return
        if len(self.state.positions) >= self.settings.max_open_positions:
            self.state.save(self.settings.state_path)
            return
        if self.state.daily_entries >= self.settings.max_daily_entries:
            self.logger.info(
                "일일 진입 횟수 한도 도달: %s/%s",
                self.state.daily_entries,
                self.settings.max_daily_entries,
            )
            self.state.save(self.settings.state_path)
            return

        slots = self.settings.max_open_positions - len(self.state.positions)
        signals = self.scan()
        equity = self._equity(cash, prices)
        opened = 0
        for signal in signals:
            if opened >= slots:
                break
            if self._buy(signal, cash, equity, now):
                opened += 1
                cash = self._cash()
        self.state.save(self.settings.state_path)

    def run_forever(self) -> None:
        self.logger.info(
            "자동매매 시작: mode=%s interval=%ss",
            self.settings.mode,
            self.settings.scan_interval_seconds,
        )
        while True:
            started = time.monotonic()
            try:
                self.run_once()
            except Exception:
                self.logger.exception("사이클 실패; 다음 주기에 재시도합니다.")
            if self._process_stop_due(datetime.now(KST)):
                self.logger.info(
                    "프로세스 종료 시각 도달: %s",
                    self.settings.process_stop_time,
                )
                return
            elapsed = time.monotonic() - started
            time.sleep(max(1, self.settings.scan_interval_seconds - elapsed))
