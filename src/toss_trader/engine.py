from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, time as clock_time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .api import TossApiError, TossClient
from .broker import Execution, LiveBroker, OrderNotFilled, PaperBroker
from .config import Settings
from .state import PendingOrder, PortfolioState, Position
from .strategy import (
    MomentumSignal,
    adaptive_shadow_evaluate,
    analyze_candidate,
    average_true_range_rate,
    completed_intraday_candles,
    continuation_entry_evaluate,
    estimated_trade_pressure,
    exit_reason,
    market_regime_allows,
    position_quantity,
    position_review_evaluate,
    recent_volume_ratio,
    rolling_vwap,
    session_breakout_allowed,
)


KST = timezone(timedelta(hours=9))

ACCOUNT_HALT_CODES = {
    "account-not-found",
    "account-restricted",
    "investor-exchange-not-integrated",
    "prerequisite-required",
}
SYMBOL_BLOCK_CODES = {
    "stock-restricted",
    "market-not-supported-for-stock",
    "order-type-not-allowed",
    "opposite-pending-order-exists",
    "price-out-of-range",
}


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
    file_handler = logging.FileHandler(log_dir / "trader.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def _parse_clock(value: str) -> clock_time:
    hour, minute = value.split(":", 1)
    return clock_time(int(hour), int(minute), tzinfo=KST)


def _safe_decimal(value: object | None) -> Decimal:
    return Decimal(str(value or "0"))


def _is_leveraged_or_inverse_etp(stock: dict) -> bool:
    security_type = str(stock.get("securityType", "")).upper()
    if security_type not in {"ETF", "FOREIGN_ETF", "ETN"}:
        return False
    factor = stock.get("leverageFactor")
    if factor is not None and factor != "":
        try:
            return Decimal(str(factor)) != Decimal("1")
        except Exception:
            return True
    name = f"{stock.get('name', '')} {stock.get('englishName', '')}".lower()
    return any(
        keyword in name
        for keyword in ("레버리지", "인버스", "곱버스", "leveraged", "inverse")
    )


class TradingEngine:
    def __init__(self, settings: Settings, client: TossClient) -> None:
        self.settings = settings
        self.client = client
        self.logger = configure_logging(settings.project_root)
        today = datetime.now(KST).date().isoformat()
        if settings.mode == "live":
            starting_cash = Decimal(str(client.buying_power()["cashBuyingPower"]))
        else:
            starting_cash = settings.paper_starting_cash_krw
        self.state = PortfolioState.load_or_fresh(
            settings.state_path, today, starting_cash
        )
        self.broker = (
            LiveBroker(client, settings.order_timeout_seconds)
            if settings.mode == "live"
            else PaperBroker(
                settings.paper_slippage_bps,
                settings.paper_commission_rate,
                settings.paper_sell_tax_rate,
            )
        )
        self._shadow_tracking_day: str | None = None
        self._shadow_tracking: list[dict] = []
        self._continuation_confirmations: dict[str, tuple[datetime, int]] = {}

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

    def _equity(self, cash: Decimal, prices: dict[str, Decimal]) -> Decimal:
        position_value = sum(
            (
                prices.get(symbol, position.entry_price) * position.quantity
                for symbol, position in self.state.positions.items()
            ),
            Decimal("0"),
        )
        return cash + position_value

    def _new_pending(
        self,
        *,
        symbol: str,
        side: str,
        quantity: int,
        reference_price: Decimal,
        now: datetime,
        reason: str | None = None,
    ) -> PendingOrder:
        pending = PendingOrder(
            client_order_id=f"tat-{now:%y%m%d}-{side.lower()}-{uuid.uuid4().hex[:10]}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            created_at=now.isoformat(),
            reference_price=reference_price,
            reason=reason,
        )
        self.state.pending_order = pending
        self.state.save(self.settings.state_path)
        return pending

    def _record_submitted(self, order_id: str) -> None:
        if self.state.pending_order is None:
            raise RuntimeError("Order callback received without a pending journal")
        self.state.pending_order.order_id = order_id
        self.state.save(self.settings.state_path)

    def _apply_buy_execution(
        self,
        pending: PendingOrder,
        execution: Execution,
        now: datetime,
        signal: MomentumSignal | None = None,
    ) -> None:
        self.state.positions[pending.symbol] = Position(
            symbol=pending.symbol,
            quantity=execution.quantity,
            entry_price=execution.price,
            high_water_price=execution.price,
            opened_at=now.isoformat(),
            entry_vwap=signal.vwap if signal is not None else None,
            breakout_reference=signal.price if signal is not None else None,
            entry_commission=execution.commission,
            entry_tax=execution.tax,
        )
        if self.settings.mode == "paper":
            self.state.cash -= (
                execution.price * Decimal(execution.quantity)
                + execution.commission
                + execution.tax
            )
            self._record_simulated_order(pending, execution, now)
        self.state.daily_entries += 1
        self.state.pending_order = None

    def _apply_sell_execution(
        self, pending: PendingOrder, execution: Execution, now: datetime
    ) -> Decimal:
        position = self.state.positions[pending.symbol]
        sold_quantity = min(execution.quantity, position.quantity)
        ratio = Decimal(sold_quantity) / Decimal(position.quantity)
        allocated_entry_cost = (
            position.entry_commission + position.entry_tax
        ) * ratio
        realized = (
            (execution.price - position.entry_price) * Decimal(sold_quantity)
            - allocated_entry_cost
            - execution.commission
            - execution.tax
        )
        self.state.realized_pnl += realized
        if self.settings.mode == "paper":
            self.state.cash += (
                execution.price * Decimal(sold_quantity)
                - execution.commission
                - execution.tax
            )
            self._record_simulated_order(pending, execution, now)
        remaining = position.quantity - sold_quantity
        if remaining == 0:
            del self.state.positions[pending.symbol]
        else:
            position.quantity = remaining
            position.entry_commission *= Decimal("1") - ratio
            position.entry_tax *= Decimal("1") - ratio
        self.state.pending_order = None
        return realized

    def _record_simulated_order(
        self, pending: PendingOrder, execution: Execution, now: datetime
    ) -> None:
        """Keep paper fills in the same order shape used by daily reports."""
        self.state.simulated_orders.append(
            {
                "orderId": execution.order_id,
                "symbol": pending.symbol,
                "side": pending.side,
                "status": "FILLED",
                "orderedAt": now.isoformat(timespec="seconds"),
                "reason": pending.reason,
                "execution": {
                    "filledQuantity": str(execution.quantity),
                    "averageFilledPrice": str(execution.price),
                    "commission": str(execution.commission),
                    "tax": str(execution.tax),
                },
            }
        )

    def _reconcile_pending(self, now: datetime) -> None:
        pending = self.state.pending_order
        if pending is None:
            return
        if self.settings.mode != "live":
            self.state.entries_halted = True
            self.state.halt_reason = "paper_pending_order_recovery_required"
            self.state.save(self.settings.state_path)
            return
        if not pending.order_id:
            self.state.entries_halted = True
            self.state.halt_reason = "unresolved_order_without_server_id"
            self.logger.error(
                "ENTRY_HALT unresolved pending order clientOrderId=%s symbol=%s",
                pending.client_order_id,
                pending.symbol,
            )
            self.state.save(self.settings.state_path)
            return

        order = self.client.order(pending.order_id)
        status = str(order.get("status", "UNKNOWN"))
        if status not in LiveBroker.TERMINAL and not order.get("canceledAt"):
            self.client.cancel_order(pending.order_id)
            time.sleep(1)
            order = self.client.order(pending.order_id)
            status = str(order.get("status", "UNKNOWN"))
        execution_data = order.get("execution", {})
        filled = int(_safe_decimal(execution_data.get("filledQuantity")))
        average = execution_data.get("averageFilledPrice")
        if filled > 0 and average is not None:
            execution = Execution(
                pending.order_id,
                filled,
                Decimal(str(average)),
                _safe_decimal(execution_data.get("commission")),
                _safe_decimal(execution_data.get("tax")),
            )
            if pending.side == "BUY":
                self._apply_buy_execution(pending, execution, now)
            elif pending.symbol in self.state.positions:
                realized = self._apply_sell_execution(pending, execution, now)
                self.logger.info(
                    "RECOVERED_EXIT symbol=%s qty=%s pnl=%s order=%s",
                    pending.symbol,
                    filled,
                    realized,
                    pending.order_id,
                )
        elif status in LiveBroker.TERMINAL or order.get("canceledAt"):
            self.state.blocked_symbols[pending.symbol] = f"not_filled:{status}"
            self.state.pending_order = None
        else:
            self.state.entries_halted = True
            self.state.halt_reason = "pending_order_reconciliation_failed"
        self.state.save(self.settings.state_path)

    def _handle_order_error(
        self, error: TossApiError, pending: PendingOrder
    ) -> None:
        reason = f"{error.code}:{error}"
        if pending.order_id:
            # An accepted order exists; leave the journal intact for the next
            # reconciliation cycle rather than guessing its final state.
            self.state.entries_halted = True
            self.state.halt_reason = "accepted_order_status_unknown"
        else:
            self.state.pending_order = None
            if error.code in ACCOUNT_HALT_CODES:
                self.state.entries_halted = True
                self.state.halt_reason = error.code
            elif error.code in SYMBOL_BLOCK_CODES:
                self.state.blocked_symbols[pending.symbol] = reason
            else:
                self.state.entries_halted = True
                self.state.halt_reason = f"order_error:{error.code}"
        self.state.last_error = reason
        self.state.save(self.settings.state_path)
        self.logger.error(
            "ORDER_REJECTED side=%s symbol=%s code=%s status=%s requestId=%s",
            pending.side,
            pending.symbol,
            error.code,
            error.status,
            error.request_id,
        )

    def _sell(
        self, symbol: str, price: Decimal, reason: str, now: datetime
    ) -> None:
        position = self.state.positions[symbol]
        quantity = position.quantity
        if self.settings.mode == "live":
            quantity = min(quantity, int(self.client.sellable_quantity(symbol)))
            if quantity <= 0:
                self.state.entries_halted = True
                self.state.halt_reason = "position_not_sellable"
                self.state.last_error = f"{symbol} has no sellable quantity"
                self.state.save(self.settings.state_path)
                self.logger.error("EXIT_BLOCKED symbol=%s no sellable quantity", symbol)
                return
        pending = self._new_pending(
            symbol=symbol,
            side="SELL",
            quantity=quantity,
            reference_price=price,
            now=now,
            reason=reason,
        )
        try:
            execution = self.broker.sell(
                symbol,
                quantity,
                reference_price=price,
                client_order_id=pending.client_order_id,
                on_submitted=self._record_submitted,
            )
        except TossApiError as exc:
            self._handle_order_error(exc, pending)
            return
        except OrderNotFilled as exc:
            self.state.pending_order = None
            self.state.last_error = str(exc)
            self.state.save(self.settings.state_path)
            self.logger.error("EXIT_NOT_FILLED symbol=%s status=%s", symbol, exc.status)
            return
        realized = self._apply_sell_execution(pending, execution, now)
        self.logger.info(
            "EXIT mode=%s symbol=%s qty=%s price=%s pnl=%s reason=%s order=%s",
            self.settings.mode,
            symbol,
            execution.quantity,
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
                self.logger.warning("POSITION_PRICE_MISSING symbol=%s", symbol)
                continue
            position.high_water_price = max(position.high_water_price, current)
            if overnight:
                self._sell(symbol, current, "overnight_recovery", now)
                continue
            if self._force_exit_due(now):
                self._sell(symbol, current, "intraday_force_exit", now)
                continue
            volatility_rate = None
            dynamic_vwap = None
            trade_pressure = None
            volume_ratio = None
            review_reason = None
            recent_candles: list[dict] = []
            candles = getattr(self.client, "candles", None)
            if candles is not None:
                try:
                    recent_candles = candles(symbol, count=30)
                    volatility_rate = average_true_range_rate(recent_candles, period=14)
                    dynamic_vwap = rolling_vwap(recent_candles, now, window=20)
                    volume_ratio = recent_volume_ratio(recent_candles, now)
                    completed = completed_intraday_candles(recent_candles, now)
                    if completed:
                        latest = completed[-1]
                        candle_at = str(latest["timestamp"])
                        if candle_at != position.last_failure_candle_at:
                            close = _safe_decimal(latest.get("closePrice"))
                            position.failure_vwap_count = (
                                position.failure_vwap_count + 1
                                if dynamic_vwap is not None and close < dynamic_vwap
                                else 0
                            )
                            position.failure_breakout_count = (
                                position.failure_breakout_count + 1
                                if position.breakout_reference is not None
                                and close < position.breakout_reference
                                else 0
                            )
                            position.last_failure_candle_at = candle_at
                except Exception as exc:
                    self.logger.warning(
                        "POSITION_VOLATILITY_UNAVAILABLE symbol=%s error=%s",
                        symbol,
                        type(exc).__name__,
                    )
            opened_at = datetime.fromisoformat(position.opened_at)
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            elapsed_seconds = (now - opened_at).total_seconds()
            paper_review_due = (
                self.settings.mode == "paper"
                and self.settings.paper_position_review_enabled
                and (
                    (
                        position.review_5m_at is None
                        and elapsed_seconds >= self.settings.paper_review_5m_seconds
                    )
                    or (
                        position.review_10m_at is None
                        and elapsed_seconds >= self.settings.paper_review_10m_seconds
                    )
                )
            )
            if (
                self.settings.failure_exit_enabled
                and (
                    position.failure_vwap_count > 0
                    or position.failure_breakout_count > 0
                )
            ) or paper_review_due:
                try:
                    trade_pressure = estimated_trade_pressure(
                        self.client.trades(symbol, count=50),
                        self.client.orderbook(symbol),
                    )
                except Exception as exc:
                    self.logger.warning(
                        "POSITION_PRESSURE_UNAVAILABLE symbol=%s error=%s",
                        symbol,
                        type(exc).__name__,
                    )
            review = position_review_evaluate(
                position,
                current,
                self.settings,
                now,
                current_vwap=dynamic_vwap,
                trade_pressure=trade_pressure,
                volume_ratio=volume_ratio,
            )
            if review is not None:
                if review.data_complete:
                    outcome = (
                        review.exit_reason
                        or ("strong_trend" if review.strong_trend else "hold")
                    )
                    if review.checkpoint == "5m":
                        position.review_5m_at = now.isoformat(timespec="seconds")
                        position.review_5m_outcome = outcome
                    else:
                        position.review_10m_at = now.isoformat(timespec="seconds")
                        position.review_10m_outcome = outcome
                    if review.strong_trend:
                        position.strong_trend_confirmed = True
                    review_reason = review.exit_reason
                    self.logger.info(
                        "POSITION_REVIEW mode=paper symbol=%s checkpoint=%s "
                        "outcome=%s gain=%s pressure=%s volume=%s",
                        symbol,
                        review.checkpoint,
                        outcome,
                        review.metrics.get("gain_rate"),
                        review.metrics.get("trade_pressure"),
                        review.metrics.get("volume_ratio"),
                    )
                    self._record_position_review(
                        symbol,
                        review,
                        outcome,
                        now,
                    )
                else:
                    self.logger.info(
                        "POSITION_REVIEW_SKIP mode=paper symbol=%s checkpoint=%s "
                        "reason=data_unavailable",
                        symbol,
                        review.checkpoint,
                    )
            reason = exit_reason(
                position,
                current,
                self.settings,
                now=now,
                volatility_rate=volatility_rate,
                failure_vwap_count=position.failure_vwap_count,
                failure_breakout_count=position.failure_breakout_count,
                trade_pressure=trade_pressure,
                failure_exit_enabled=self.settings.failure_exit_enabled,
            )
            reason = reason or review_reason
            if reason:
                self._sell(symbol, current, reason, now)

    def _record_position_review(
        self,
        symbol: str,
        review,
        outcome: str,
        now: datetime,
    ) -> None:
        """Persist completed paper checkpoints for later weekly comparison."""
        try:
            directory = self.settings.project_root / "reports" / "position_reviews"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{now.date().isoformat()}.jsonl"
            record = {
                "timestamp": now.isoformat(timespec="seconds"),
                "symbol": symbol,
                "checkpoint": review.checkpoint,
                "outcome": outcome,
                "exit_reason": review.exit_reason,
                "strong_trend": review.strong_trend,
                "metrics": review.metrics,
            }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            self.logger.warning(
                "POSITION_REVIEW_RECORD_FAILED symbol=%s error=%s",
                symbol,
                type(exc).__name__,
            )

    def _daily_guard(
        self, cash: Decimal, prices: dict[str, Decimal]
    ) -> Decimal:
        equity = self._equity(cash, prices)
        if self.state.initial_equity <= 0:
            return Decimal("0")
        pnl_rate = equity / self.state.initial_equity - Decimal("1")
        loss_limit_rate = self.settings.max_daily_loss_rate
        if self.settings.max_daily_loss_krw > 0 and self.state.initial_equity > 0:
            loss_limit_rate = self.settings.max_daily_loss_krw / self.state.initial_equity
        if pnl_rate <= -loss_limit_rate:
            self.state.entries_halted = True
            self.state.halt_reason = "daily_loss_limit"
        elif pnl_rate >= self.settings.max_daily_profit_lock_rate:
            self.state.entries_halted = True
            self.state.halt_reason = "daily_profit_lock"
        if self.state.entries_halted:
            self.logger.warning(
                "ENTRY_HALT reason=%s daily_pnl_rate=%.4f",
                self.state.halt_reason,
                pnl_rate,
            )
        return pnl_rate

    def _market_regime_ok(self, now: datetime) -> bool:
        if not self.settings.market_regime_filter:
            return True
        candles = {
            symbol: self.client.market_indicator_candles(symbol, count=20)
            for symbol in ("KOSPI", "KOSDAQ")
        }
        allowed = market_regime_allows(candles, self.settings, now)
        if not allowed:
            self.logger.info("ENTRY_SKIP market_regime_filter")
        return allowed

    def _manual_holding_symbols(self) -> set[str]:
        if self.settings.mode != "live":
            return set()
        result = self.client.holdings()
        symbols: set[str] = set()

        def collect(value: object) -> None:
            if isinstance(value, dict):
                symbol = value.get("symbol")
                if symbol:
                    symbols.add(str(symbol))
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(result)
        return symbols - set(self.state.positions)

    def scan(
        self,
        now: datetime | None = None,
        excluded_symbols: set[str] | None = None,
    ) -> list[MomentumSignal]:
        now = now or datetime.now(KST)
        if not self._market_regime_ok(now):
            return []
        excluded = (excluded_symbols or set()) | set(self.state.blocked_symbols)
        signals: list[MomentumSignal] = []
        rankings = self.client.rankings(self.settings.ranking_count)
        stock_info = {
            str(item["symbol"]): item
            for item in self.client.stocks([str(item["symbol"]) for item in rankings])
            if item.get("symbol")
        }
        shadow_count = 0
        for ranking in rankings:
            symbol = str(ranking["symbol"])
            if symbol in self.state.positions or symbol in excluded:
                continue
            instrument = stock_info.get(symbol)
            if instrument is None:
                self.logger.info(
                    "ENTRY_SKIP instrument_metadata_missing symbol=%s", symbol
                )
                continue
            if _is_leveraged_or_inverse_etp(instrument):
                self.logger.info(
                    "ENTRY_SKIP leveraged_inverse_etp symbol=%s", symbol
                )
                continue
            if Decimal(str(ranking["price"]["lastPrice"])) > self.settings.max_trade_krw:
                continue
            if self.client.stock_warnings(symbol):
                continue
            try:
                candles = self.client.candles(
                    symbol, count=self.settings.candle_lookback_count
                )
            except TossApiError as exc:
                self.logger.warning(
                    "ENTRY_SKIP candle_api_error symbol=%s code=%s status=%s",
                    symbol,
                    exc.code,
                    exc.status,
                )
                continue
            final_window = now.timetz().hour >= 14
            shadow_orderbook = None
            continuation = None
            continuation_confirmed = False
            continuation_confirmation_count = 0
            if (
                self.settings.adaptive_shadow_enabled
                and shadow_count < self.settings.adaptive_shadow_max_candidates
            ):
                shadow_count += 1
                try:
                    shadow_orderbook = self.client.orderbook(symbol)
                    shadow_trades = self.client.trades(symbol, count=50)
                    evaluation = adaptive_shadow_evaluate(
                        ranking,
                        candles,
                        shadow_orderbook,
                        shadow_trades,
                        self.settings,
                        now,
                        True,
                    )
                    if (
                        self.settings.mode == "paper"
                        and self.settings.paper_continuation_entry_enabled
                        and not final_window
                    ):
                        continuation = continuation_entry_evaluate(
                            candles,
                            evaluation,
                            self.settings,
                            now,
                        )
                        (
                            continuation_confirmation_count,
                            continuation_confirmed,
                        ) = self._update_continuation_confirmation(
                            symbol,
                            continuation.eligible,
                            now,
                        )
                    self._record_adaptive_shadow(
                        evaluation,
                        now,
                        continuation=continuation,
                        continuation_confirmation_count=(
                            continuation_confirmation_count
                        ),
                        continuation_confirmed=continuation_confirmed,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "ADAPTIVE_SHADOW_SKIP symbol=%s error=%s",
                        symbol,
                        type(exc).__name__,
                    )
            strict_breakout = session_breakout_allowed(
                candles,
                now,
                final_window,
                self.settings.breakout_confirmation_candles,
            )
            paper_continuation = (
                not strict_breakout
                and self.settings.mode == "paper"
                and not final_window
                and self.state.daily_entries == 0
                and continuation_confirmed
            )
            if not strict_breakout and not paper_continuation:
                details = ""
                if continuation is not None:
                    details = (
                        " continuation_reasons="
                        + ",".join(continuation.rejection_reasons or ("confirming",))
                        + f" confirmation={continuation_confirmation_count}/"
                        f"{self.settings.continuation_confirmation_evaluations}"
                    )
                self.logger.info(
                    "ENTRY_SKIP session_breakout_filter symbol=%s final=%s%s",
                    symbol,
                    final_window,
                    details,
                )
                continue
            if paper_continuation:
                self.logger.info(
                    "ENTRY_PATH paper_continuation symbol=%s confirmation=%s/%s",
                    symbol,
                    continuation_confirmation_count,
                    self.settings.continuation_confirmation_evaluations,
                )
            orderbook = shadow_orderbook or self.client.orderbook(symbol)
            signal = analyze_candidate(
                ranking, candles, orderbook, self.settings, as_of=now
            )
            if signal is not None:
                signals.append(signal)
            elif paper_continuation:
                self.logger.info(
                    "ENTRY_SKIP continuation_signal_filter symbol=%s", symbol
                )
        return sorted(signals, key=lambda item: item.score, reverse=True)

    def _update_continuation_confirmation(
        self, symbol: str, eligible: bool, now: datetime
    ) -> tuple[int, bool]:
        if not eligible:
            self._continuation_confirmations.pop(symbol, None)
            return 0, False
        previous = self._continuation_confirmations.get(symbol)
        max_gap = max(90, self.settings.scan_interval_seconds * 3)
        count = 1
        if previous is not None:
            previous_at, previous_count = previous
            gap = (now - previous_at).total_seconds()
            if previous_at.date() == now.date() and 0 < gap <= max_gap:
                count = previous_count + 1
        self._continuation_confirmations[symbol] = (now, count)
        return (
            count,
            count >= self.settings.continuation_confirmation_evaluations,
        )

    def _record_adaptive_shadow(
        self,
        evaluation,
        now: datetime,
        *,
        continuation=None,
        continuation_confirmation_count: int = 0,
        continuation_confirmed: bool = False,
    ) -> None:
        """Persist shadow and paper-continuation evidence."""
        try:
            day = now.date().isoformat()
            directory = self.settings.project_root / "reports" / "filter_funnel"
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{day}.jsonl"
            record = {
                "timestamp": now.isoformat(timespec="seconds"),
                "symbol": evaluation.symbol,
                "live_pass": evaluation.live_pass,
                "shadow_pass": evaluation.shadow_pass,
                "rejection_reasons": list(evaluation.rejection_reasons),
                "scores": {
                    "entry": str(evaluation.entry_score),
                    "breakout": str(evaluation.breakout_score),
                    "volume": str(evaluation.volume_score),
                    "vwap": str(evaluation.vwap_score),
                    "orderbook": str(evaluation.orderbook_score),
                    "trade_pressure": str(evaluation.trade_pressure_score),
                    "market_context": str(evaluation.market_context_score),
                },
                "metrics": evaluation.metrics,
            }
            if continuation is not None:
                record["continuation"] = {
                    "paper_only": True,
                    "eligible": continuation.eligible,
                    "confirmed": continuation_confirmed,
                    "confirmation_count": continuation_confirmation_count,
                    "morning_entry_available": self.state.daily_entries == 0,
                    "rejection_reasons": list(continuation.rejection_reasons),
                    "metrics": continuation.metrics,
                }
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            if evaluation.shadow_pass:
                self._register_shadow_candidate(evaluation, now)
        except Exception as exc:
            self.logger.warning("ADAPTIVE_SHADOW_RECORD_FAILED error=%s", type(exc).__name__)

    def _shadow_tracking_path(self, day: str) -> Path:
        return (
            self.settings.project_root
            / "reports"
            / "shadow_tracking"
            / f"{day}.json"
        )

    def _ensure_shadow_tracking(self, day: str) -> None:
        if self._shadow_tracking_day == day:
            return
        path = self._shadow_tracking_path(day)
        self._shadow_tracking_day = day
        self._shadow_tracking = []
        if not path.exists():
            return
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                self._shadow_tracking = loaded
        except Exception as exc:
            self.logger.warning(
                "SHADOW_TRACKING_LOAD_FAILED day=%s error=%s",
                day,
                type(exc).__name__,
            )

    def _save_shadow_tracking(self) -> None:
        if self._shadow_tracking_day is None:
            return
        path = self._shadow_tracking_path(self._shadow_tracking_day)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self._shadow_tracking, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _register_shadow_candidate(self, evaluation, now: datetime) -> None:
        reference_price = _safe_decimal(
            evaluation.metrics.get("reference_price")
        )
        if reference_price <= 0:
            return
        day = now.date().isoformat()
        self._ensure_shadow_tracking(day)
        if any(
            item.get("symbol") == evaluation.symbol
            and not item.get("completed", False)
            for item in self._shadow_tracking
        ):
            return
        self._shadow_tracking.append(
            {
                "symbol": evaluation.symbol,
                "observed_at": now.isoformat(timespec="seconds"),
                "reference_price": str(reference_price),
                "entry_score": str(evaluation.entry_score),
                "forward_returns": {},
                "mfe": "0",
                "mae": "0",
                "completed": False,
            }
        )
        self._save_shadow_tracking()

    def _update_shadow_tracking(self, now: datetime) -> None:
        """Measure rejected/alternate candidates without influencing orders."""
        day = now.date().isoformat()
        self._ensure_shadow_tracking(day)
        active = [
            item for item in self._shadow_tracking
            if not item.get("completed", False)
        ]
        if not active:
            return
        try:
            quote_rows = self.client.prices(
                sorted({str(item["symbol"]) for item in active})
            )
            quotes = {
                str(item["symbol"]): _safe_decimal(item.get("lastPrice"))
                for item in quote_rows
            }
        except Exception as exc:
            self.logger.warning(
                "SHADOW_TRACKING_PRICE_FAILED error=%s", type(exc).__name__
            )
            return

        changed = False
        for item in active:
            current = quotes.get(str(item["symbol"]), Decimal("0"))
            reference = _safe_decimal(item.get("reference_price"))
            if current <= 0 or reference <= 0:
                continue
            observed_at = datetime.fromisoformat(str(item["observed_at"]))
            elapsed_minutes = (now - observed_at).total_seconds() / 60
            if elapsed_minutes < 0:
                continue
            forward_return = current / reference - Decimal("1")
            item["mfe"] = str(max(_safe_decimal(item.get("mfe")), forward_return))
            item["mae"] = str(min(_safe_decimal(item.get("mae")), forward_return))
            checkpoints = item.setdefault("forward_returns", {})
            for minute in (5, 10, 15, 30):
                key = f"{minute}m"
                if elapsed_minutes >= minute and key not in checkpoints:
                    checkpoints[key] = str(forward_return)
                    changed = True
            if elapsed_minutes >= 30 and len(checkpoints) == 4:
                item["completed"] = True
                item["completed_at"] = now.isoformat(timespec="seconds")
                changed = True
                self.logger.info(
                    "SHADOW_OUTCOME_COMPLETE symbol=%s r30=%s mfe=%s mae=%s",
                    item["symbol"],
                    checkpoints["30m"],
                    item["mfe"],
                    item["mae"],
                )
        if active:
            changed = True
        if changed:
            self._save_shadow_tracking()

    def _fresh_entry_quote(
        self, signal: MomentumSignal, now: datetime
    ) -> tuple[Decimal, int] | None:
        prices = self.client.prices([signal.symbol])
        if not prices:
            return None
        price_timestamp = datetime.fromisoformat(str(prices[0]["timestamp"]))
        if abs((now - price_timestamp).total_seconds()) > self.settings.max_data_age_seconds:
            self.logger.info("ENTRY_SKIP stale_price symbol=%s", signal.symbol)
            return None
        orderbook = self.client.orderbook(signal.symbol)
        book_timestamp = datetime.fromisoformat(str(orderbook["timestamp"]))
        if abs((now - book_timestamp).total_seconds()) > self.settings.max_data_age_seconds:
            self.logger.info("ENTRY_SKIP stale_orderbook symbol=%s", signal.symbol)
            return None
        asks = sorted(
            (
                (Decimal(str(item["price"])), int(Decimal(str(item["volume"]))))
                for item in orderbook.get("asks", [])
            ),
            key=lambda item: item[0],
        )
        if not asks:
            return None
        best_ask, best_ask_volume = asks[0]
        baseline = signal.best_ask or signal.price
        if best_ask > baseline * (Decimal("1") + self.settings.max_entry_slippage_rate):
            self.logger.info(
                "ENTRY_SKIP quote_moved symbol=%s baseline=%s ask=%s",
                signal.symbol,
                baseline,
                best_ask,
            )
            return None
        return best_ask, best_ask_volume

    def _buy(
        self,
        signal: MomentumSignal,
        cash: Decimal,
        equity: Decimal,
        now: datetime,
    ) -> bool:
        quote = self._fresh_entry_quote(signal, now)
        if quote is None:
            return False
        best_ask, best_ask_volume = quote
        quantity = position_quantity(
            cash=cash,
            equity=equity,
            price=best_ask,
            settings=self.settings,
            stop_rate=signal.risk_stop_rate,
        )
        quantity = min(quantity, best_ask_volume)
        if quantity <= 0:
            self.logger.info("ENTRY_SKIP insufficient_budget symbol=%s", signal.symbol)
            return False
        pending = self._new_pending(
            symbol=signal.symbol,
            side="BUY",
            quantity=quantity,
            reference_price=best_ask,
            now=now,
        )
        try:
            execution = self.broker.buy(
                signal.symbol,
                quantity,
                reference_price=best_ask,
                client_order_id=pending.client_order_id,
                on_submitted=self._record_submitted,
            )
        except TossApiError as exc:
            self._handle_order_error(exc, pending)
            return False
        except OrderNotFilled as exc:
            self.state.pending_order = None
            self.state.blocked_symbols[signal.symbol] = f"not_filled:{exc.status}"
            self.state.last_error = str(exc)
            self.state.save(self.settings.state_path)
            self.logger.info(
                "ENTRY_NOT_FILLED symbol=%s status=%s", signal.symbol, exc.status
            )
            return False
        self._apply_buy_execution(pending, execution, now, signal)
        self.logger.info(
            "ENTRY mode=%s symbol=%s qty=%s price=%s score=%.4f "
            "m5=%.4f m15=%.4f volume=%.2f spread=%.4f proxy=%s/4 order=%s",
            self.settings.mode,
            signal.symbol,
            execution.quantity,
            execution.price,
            signal.score,
            signal.momentum_5m,
            signal.momentum_15m,
            signal.volume_surge,
            signal.spread_rate,
            signal.institutional_proxy_score,
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
        self._reconcile_pending(now)
        if self.state.pending_order is not None:
            return
        self._update_shadow_tracking(now)

        prices = self._prices_for_positions()
        self._manage_positions(prices, now)
        if self.state.pending_order is not None:
            return
        prices = self._prices_for_positions()
        cash = self._cash()
        if self.settings.mode == "live":
            self.state.cash = cash
        if self.state.trading_day != now.date().isoformat() and not self.state.positions:
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
                "ENTRY_SKIP daily_limit=%s/%s",
                self.state.daily_entries,
                self.settings.max_daily_entries,
            )
            self.state.save(self.settings.state_path)
            return

        if self.settings.mode == "live":
            open_orders = self.client.list_orders("OPEN")
            if open_orders:
                self.logger.warning(
                    "ENTRY_SKIP account_has_open_orders count=%s", len(open_orders)
                )
                self.state.save(self.settings.state_path)
                return
        excluded = self._manual_holding_symbols()
        slots = self.settings.max_open_positions - len(self.state.positions)
        signals = self.scan(now=now, excluded_symbols=excluded)
        equity = self._equity(cash, prices)
        opened = 0
        for signal in signals:
            if opened >= slots or self.state.entries_halted:
                break
            if self._buy(signal, cash, equity, now):
                opened += 1
                cash = self._cash()
        self.state.save(self.settings.state_path)

    def run_forever(self) -> None:
        self.logger.info(
            "AUTO_TRADING_START mode=%s interval=%ss",
            self.settings.mode,
            self.settings.scan_interval_seconds,
        )
        while True:
            started = time.monotonic()
            try:
                self.run_once()
                self.state.consecutive_errors = 0
            except Exception as exc:
                self.state.consecutive_errors += 1
                self.state.last_error = f"{type(exc).__name__}: {exc}"
                self.logger.exception(
                    "CYCLE_FAILED consecutive=%s/%s",
                    self.state.consecutive_errors,
                    self.settings.max_consecutive_errors,
                )
                if (
                    self.state.consecutive_errors
                    >= self.settings.max_consecutive_errors
                ):
                    self.state.entries_halted = True
                    self.state.halt_reason = "unexpected_error_circuit_breaker"
            self.state.save(self.settings.state_path)
            heartbeat = self.settings.project_root / "state" / f"{self.settings.mode}_heartbeat.json"
            heartbeat.write_text(
                json.dumps({"updated_at": datetime.now(KST).isoformat()}),
                encoding="utf-8",
            )
            if self._process_stop_due(datetime.now(KST)):
                self.logger.info(
                    "AUTO_TRADING_STOP scheduled=%s",
                    self.settings.process_stop_time,
                )
                try:
                    from .reporting import write_daily_report

                    write_daily_report(self.settings, self.state, self.client)
                except Exception:
                    self.logger.exception("DAILY_REPORT_FAILED")
                return
            elapsed = time.monotonic() - started
            time.sleep(max(1, self.settings.scan_interval_seconds - elapsed))
