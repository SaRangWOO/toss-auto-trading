from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any

from .config import Settings
from .state import Position


ZERO = Decimal("0")


def D(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class MomentumSignal:
    symbol: str
    price: Decimal
    score: Decimal
    daily_change_rate: Decimal
    momentum_5m: Decimal
    momentum_15m: Decimal
    volume_surge: Decimal
    vwap: Decimal
    spread_rate: Decimal
    institutional_proxy_score: int
    best_ask: Decimal | None = None
    orderbook_timestamp: str | None = None
    risk_stop_rate: Decimal = ZERO


@dataclass(frozen=True)
class AdaptiveShadowEvaluation:
    symbol: str
    live_pass: bool
    shadow_pass: bool
    rejection_reasons: tuple[str, ...]
    breakout_score: Decimal
    volume_score: Decimal
    vwap_score: Decimal
    orderbook_score: Decimal
    trade_pressure_score: Decimal
    market_context_score: Decimal
    entry_score: Decimal
    metrics: dict[str, str]


@dataclass(frozen=True)
class ContinuationEvaluation:
    eligible: bool
    rejection_reasons: tuple[str, ...]
    metrics: dict[str, str]


def _return(current: Decimal, previous: Decimal) -> Decimal:
    if previous <= 0:
        return ZERO
    return (current / previous) - Decimal("1")


def analyze_candidate(
    ranking: dict[str, Any],
    candles: list[dict[str, Any]],
    orderbook: dict[str, Any],
    settings: Settings,
    as_of: datetime | None = None,
) -> MomentumSignal | None:
    if len(candles) < 16:
        return None
    ordered_all = sorted(candles, key=lambda item: item["timestamp"])
    if as_of is not None:
        # The most recent 1-minute candle is still forming until the next
        # minute. Using it creates false volume spikes and look-ahead bias.
        ordered_all = [
            item
            for item in ordered_all
            if datetime.fromisoformat(str(item["timestamp"]))
            .replace(second=0, microsecond=0)
            < as_of.replace(second=0, microsecond=0)
        ]
        if len(ordered_all) < 16:
            return None
        newest_at = datetime.fromisoformat(str(ordered_all[-1]["timestamp"]))
        if (as_of - newest_at).total_seconds() > settings.max_data_age_seconds:
            return None
    latest_day = datetime.fromisoformat(
        str(ordered_all[-1]["timestamp"])
    ).date()
    ordered = [
        item
        for item in ordered_all
        if datetime.fromisoformat(str(item["timestamp"])).date() == latest_day
    ]
    # Do not calculate opening momentum across the overnight gap.
    if len(ordered) < 16:
        return None
    closes = [D(item["closePrice"]) for item in ordered]
    volumes = [D(item["volume"]) for item in ordered]
    latest = closes[-1]
    if latest <= 0:
        return None

    daily_change = D(ranking["price"]["changeRate"])
    trading_amount = D(ranking["tradingAmount"])
    momentum_5m = _return(latest, closes[-6])
    momentum_15m = _return(latest, closes[-16])

    prior_volumes = volumes[-11:-1]
    median_volume = D(statistics.median(prior_volumes)) if prior_volumes else ZERO
    volume_surge = volumes[-1] / median_volume if median_volume > 0 else ZERO

    recent = ordered[-20:]
    total_volume = sum((D(item["volume"]) for item in recent), ZERO)
    vwap = (
        sum(
            (
                D(item["closePrice"]) * D(item["volume"])
                for item in recent
            ),
            ZERO,
        )
        / total_volume
        if total_volume > 0
        else latest
    )
    over_vwap = _return(latest, vwap)

    asks = [D(item["price"]) for item in orderbook.get("asks", [])]
    bids = [D(item["price"]) for item in orderbook.get("bids", [])]
    if not asks or not bids:
        return None
    best_ask = min(asks)
    best_bid = max(bids)
    midpoint = (best_ask + best_bid) / Decimal("2")
    spread_rate = (best_ask - best_bid) / midpoint if midpoint > 0 else Decimal("1")

    ask_volume = sum(
        (D(item.get("volume", "0")) for item in orderbook.get("asks", [])[:5]),
        ZERO,
    )
    bid_volume = sum(
        (D(item.get("volume", "0")) for item in orderbook.get("bids", [])[:5]),
        ZERO,
    )
    depth_total = bid_volume + ask_volume
    orderbook_imbalance = (
        (bid_volume - ask_volume) / depth_total
        if depth_total > ZERO
        else -Decimal("1")
    )

    # Three completed candles holding above their own preceding 10-candle VWAP
    # is used as persistence evidence. It is a proxy, not investor identity.
    hold_count = 0
    for index in range(max(10, len(ordered) - 3), len(ordered)):
        baseline = ordered[max(0, index - 10) : index]
        baseline_volume = sum((D(item["volume"]) for item in baseline), ZERO)
        baseline_vwap = (
            sum(
                (D(item["closePrice"]) * D(item["volume"]) for item in baseline),
                ZERO,
            )
            / baseline_volume
            if baseline_volume > ZERO
            else ZERO
        )
        if baseline_vwap > ZERO and D(ordered[index]["closePrice"]) >= baseline_vwap:
            hold_count += 1

    institutional_proxy_score = sum(
        (
            volume_surge >= settings.min_volume_surge,
            over_vwap > ZERO,
            orderbook_imbalance >= settings.min_orderbook_imbalance_rate,
            hold_count >= 3,
        )
    )
    atr_rate = average_true_range_rate(ordered, period=14) or settings.min_volatility_rate
    risk_stop_rate = max(
        settings.stop_loss_rate,
        min(atr_rate * settings.atr_stop_multiplier, settings.max_stop_loss_rate),
    )

    if not (
        settings.min_trading_amount_krw <= trading_amount
        and settings.min_daily_change_rate
        <= daily_change
        <= settings.max_daily_change_rate
        and settings.min_5m_momentum_rate
        <= momentum_5m
        <= settings.max_5m_momentum_rate
        and settings.min_15m_momentum_rate
        <= momentum_15m
        <= settings.max_15m_momentum_rate
        and volume_surge >= settings.min_volume_surge
        and ZERO < over_vwap <= settings.max_price_over_vwap_rate
        and spread_rate <= settings.max_spread_rate
        and (
            not settings.institutional_proxy_filter
            or institutional_proxy_score >= settings.min_institutional_proxy_score
        )
    ):
        return None

    score = (
        momentum_5m * Decimal("4")
        + momentum_15m * Decimal("2")
        + daily_change
        + min(volume_surge, Decimal("5")) / Decimal("100")
        - spread_rate * Decimal("5")
    )
    return MomentumSignal(
        symbol=str(ranking["symbol"]),
        price=latest,
        score=score,
        daily_change_rate=daily_change,
        momentum_5m=momentum_5m,
        momentum_15m=momentum_15m,
        volume_surge=volume_surge,
        vwap=vwap,
        spread_rate=spread_rate,
        institutional_proxy_score=institutional_proxy_score,
        best_ask=best_ask,
        orderbook_timestamp=orderbook.get("timestamp"),
        risk_stop_rate=risk_stop_rate,
    )


def market_regime_allows(
    candles_by_symbol: dict[str, list[dict[str, Any]]],
    settings: Settings,
    as_of: datetime,
) -> bool:
    """Reject entries only when both Korean indices are in a sharp downswing."""
    weak_indices = 0
    available_indices = 0
    for candles in candles_by_symbol.values():
        ordered = sorted(candles, key=lambda item: item["timestamp"])
        completed = [
            item
            for item in ordered
            if datetime.fromisoformat(str(item["timestamp"]))
            .replace(second=0, microsecond=0)
            < as_of.replace(second=0, microsecond=0)
        ]
        if len(completed) < 16:
            continue
        newest_at = datetime.fromisoformat(str(completed[-1]["timestamp"]))
        if (as_of - newest_at).total_seconds() > settings.max_data_age_seconds:
            continue
        closes = [D(item["closePrice"]) for item in completed]
        momentum_5m = _return(closes[-1], closes[-6])
        momentum_15m = _return(closes[-1], closes[-16])
        available_indices += 1
        if (
            momentum_5m < settings.min_market_5m_rate
            or momentum_15m < settings.min_market_15m_rate
        ):
            weak_indices += 1
    # Missing or stale regime data is not treated as permission to trade.
    return available_indices == 2 and weak_indices < 2


def position_quantity(
    *,
    cash: Decimal,
    equity: Decimal,
    price: Decimal,
    settings: Settings,
    stop_rate: Decimal | None = None,
) -> int:
    if cash <= 0 or equity <= 0 or price <= 0:
        return 0
    effective_stop = stop_rate or settings.stop_loss_rate
    risk_limited = equity * settings.risk_per_trade_rate / effective_stop
    allocation_limited = equity * settings.max_position_rate
    budget = min(
        settings.max_trade_krw,
        risk_limited,
        allocation_limited,
        cash * Decimal("0.98"),
    )
    if budget < price:
        return 0
    return int((budget / price).to_integral_value(rounding=ROUND_DOWN))


def average_true_range_rate(
    candles: list[dict[str, Any]], period: int = 14
) -> Decimal | None:
    """Return recent ATR as a fraction of the latest close price."""
    ordered = sorted(candles, key=lambda item: item["timestamp"])
    if len(ordered) < period + 1:
        return None
    true_ranges: list[Decimal] = []
    for previous, current in zip(ordered[-period - 1 : -1], ordered[-period:]):
        close = D(current.get("closePrice"))
        previous_close = D(previous.get("closePrice"))
        high = D(current.get("highPrice", close))
        low = D(current.get("lowPrice", close))
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
    latest = D(ordered[-1].get("closePrice"))
    if latest <= ZERO:
        return None
    return sum(true_ranges, ZERO) / D(len(true_ranges)) / latest


def completed_intraday_candles(
    candles: list[dict[str, Any]], as_of: datetime
) -> list[dict[str, Any]]:
    """Return only completed candles from the current trading day."""
    minute = as_of.replace(second=0, microsecond=0)
    return [
        item
        for item in sorted(candles, key=lambda value: value["timestamp"])
        if datetime.fromisoformat(str(item["timestamp"])).date() == as_of.date()
        and datetime.fromisoformat(str(item["timestamp"])).replace(
            second=0, microsecond=0
        ) < minute
    ]


def rolling_vwap(
    candles: list[dict[str, Any]], as_of: datetime, window: int = 20
) -> Decimal | None:
    completed = completed_intraday_candles(candles, as_of)[-window:]
    total_volume = sum((D(item.get("volume", "0")) for item in completed), ZERO)
    if not completed or total_volume <= ZERO:
        return None
    return sum(
        (
            D(item.get("closePrice", "0")) * D(item.get("volume", "0"))
            for item in completed
        ),
        ZERO,
    ) / total_volume


def estimated_trade_pressure(
    trades: list[dict[str, Any]], orderbook: dict[str, Any]
) -> Decimal | None:
    """Estimate buy pressure from trades around the midpoint; not investor flow."""
    asks = [D(item["price"]) for item in orderbook.get("asks", [])]
    bids = [D(item["price"]) for item in orderbook.get("bids", [])]
    if not trades or not asks or not bids:
        return None
    midpoint = (min(asks) + max(bids)) / Decimal("2")
    signed = [
        D(item.get("volume", "0"))
        * (Decimal("1") if D(item.get("price", "0")) >= midpoint else Decimal("-1"))
        for item in trades
    ]
    gross = sum((abs(value) for value in signed), ZERO)
    if gross <= ZERO:
        return None
    return _clamp((sum(signed, ZERO) / gross + Decimal("1")) / Decimal("2"))


def session_breakout_allowed(
    candles: list[dict[str, Any]],
    as_of: datetime,
    final_window: bool,
    confirmation_candles: int = 1,
) -> bool:
    """Require an opening-range or late-session high-volume breakout."""
    completed = [
        item
        for item in sorted(candles, key=lambda item: item["timestamp"])
        if datetime.fromisoformat(str(item["timestamp"])).replace(
            second=0, microsecond=0
        ) < as_of.replace(second=0, microsecond=0)
    ]
    today = [
        item
        for item in completed
        if datetime.fromisoformat(str(item["timestamp"])).date() == as_of.date()
    ]
    if len(today) < 10:
        return False

    def high(item: dict[str, Any]) -> Decimal:
        return D(item.get("highPrice", item.get("closePrice", "0")))

    latest = today[-1]
    latest_price = D(latest.get("closePrice", "0"))
    if latest_price <= ZERO:
        return False
    if final_window:
        confirmation = max(1, confirmation_candles)
        prior = today[:-confirmation]
        if len(prior) < 25 or len(today) < 5:
            return False
        prior_high = max((high(item) for item in prior), default=ZERO)
        blocks = [
            sum(
                (D(item.get("volume", "0")) for item in prior[index - 5 : index]),
                ZERO,
            )
            for index in range(len(prior) - 20, len(prior) + 1, 5)
        ]
        baseline = blocks[:-1]
        median_volume = D(statistics.median(baseline)) if baseline else ZERO
        latest_volume = sum(
            (D(item.get("volume", "0")) for item in today[-5:]), ZERO
        )
        return (
            all(
                D(item.get("closePrice", "0")) > prior_high
                for item in today[-confirmation:]
            )
            and median_volume > ZERO
            and latest_volume / median_volume >= Decimal("2")
        )
    opening = [
        item
        for item in today
        if datetime.fromisoformat(str(item["timestamp"])).time().hour == 9
        and datetime.fromisoformat(str(item["timestamp"])).time().minute < 30
    ]
    if not opening:
        return False
    opening_high = max((high(item) for item in opening), default=ZERO)
    confirmation = max(1, confirmation_candles)
    before_confirmation = len(today) - confirmation - 1
    previous_price = (
        D(today[before_confirmation].get("closePrice", "0"))
        if before_confirmation >= 0
        else ZERO
    )
    confirmed = [
        D(item.get("closePrice", "0")) > opening_high
        for item in today[-confirmation:]
    ]
    return (
        len(confirmed) == confirmation
        and all(confirmed)
        and previous_price <= opening_high
    )


def continuation_entry_evaluate(
    candles: list[dict[str, Any]],
    evaluation: AdaptiveShadowEvaluation,
    settings: Settings,
    as_of: datetime,
) -> ContinuationEvaluation:
    """Evaluate a conservative post-breakout continuation for paper trials."""
    today = completed_intraday_candles(candles, as_of)
    reasons: list[str] = []
    if len(today) < 16:
        return ContinuationEvaluation(
            False,
            ("insufficient_candles",),
            {"completed_candles": str(len(today))},
        )

    def timestamp(item: dict[str, Any]) -> datetime:
        return datetime.fromisoformat(str(item["timestamp"]))

    def high(item: dict[str, Any]) -> Decimal:
        return D(item.get("highPrice", item.get("closePrice", "0")))

    opening = [
        item
        for item in today
        if timestamp(item).time().hour == 9
        and timestamp(item).time().minute < 30
    ]
    if not opening:
        return ContinuationEvaluation(
            False,
            ("opening_range_unavailable",),
            {"completed_candles": str(len(today))},
        )
    opening_high = max((high(item) for item in opening), default=ZERO)
    hold_count = sum(
        D(item.get("closePrice", "0")) > opening_high for item in today[-2:]
    )
    if hold_count < 2:
        reasons.append("opening_range_hold_failed")

    breakout_at: datetime | None = None
    for index, item in enumerate(today):
        item_at = timestamp(item)
        if item_at.time().hour < 10 or index == 0:
            continue
        prior_high = max((high(value) for value in today[:index]), default=ZERO)
        if prior_high > ZERO and D(item.get("closePrice", "0")) > prior_high:
            breakout_at = item_at
    breakout_age = None
    if breakout_at is None:
        reasons.append("recent_breakout_unavailable")
    else:
        breakout_age = Decimal(str((as_of - breakout_at).total_seconds())) / Decimal("60")
        if breakout_age < ZERO or breakout_age > D(
            settings.continuation_breakout_max_age_minutes
        ):
            reasons.append("breakout_age_failed")
    opening_retest_seen = False
    if breakout_at is not None:
        opening_retest_seen = any(
            timestamp(item) >= breakout_at
            and D(item.get("lowPrice", item.get("closePrice", "0")))
            <= opening_high
            and D(item.get("closePrice", "0")) > opening_high
            for item in today
        )

    vwap_distance = D(evaluation.metrics.get("vwap_distance", "0"))
    breakout_distance = D(evaluation.metrics.get("breakout_pct", "0"))
    if evaluation.entry_score < settings.continuation_min_entry_score:
        reasons.append("continuation_entry_score_failed")
    if evaluation.volume_score < settings.continuation_min_volume_score:
        reasons.append("continuation_volume_score_failed")
    if (
        evaluation.trade_pressure_score
        < settings.continuation_min_trade_pressure_score
    ):
        reasons.append("continuation_trade_pressure_failed")
    if evaluation.orderbook_score < settings.continuation_min_orderbook_score:
        reasons.append("continuation_orderbook_failed")
    if not ZERO < vwap_distance <= settings.continuation_max_vwap_distance:
        reasons.append("continuation_vwap_distance_failed")
    if not ZERO < breakout_distance <= settings.continuation_max_breakout_distance:
        reasons.append("continuation_breakout_distance_failed")

    return ContinuationEvaluation(
        eligible=not reasons,
        rejection_reasons=tuple(reasons),
        metrics={
            "opening_high": str(opening_high),
            "opening_hold_count": str(hold_count),
            "opening_retest_seen": str(opening_retest_seen).lower(),
            "breakout_at": breakout_at.isoformat() if breakout_at else "",
            "breakout_age_minutes": str(breakout_age) if breakout_age is not None else "",
            "vwap_distance": str(vwap_distance),
            "breakout_distance": str(breakout_distance),
        },
    )


def _clamp(value: Decimal) -> Decimal:
    return max(ZERO, min(Decimal("1"), value))


def _percentile(value: Decimal, values: list[Decimal]) -> Decimal:
    if not values:
        return ZERO
    below = sum(item <= value for item in values)
    return D(below) / D(len(values))


def adaptive_shadow_evaluate(
    ranking: dict[str, Any],
    candles: list[dict[str, Any]],
    orderbook: dict[str, Any] | None,
    trades: list[dict[str, Any]] | None,
    settings: Settings,
    as_of: datetime,
    market_allowed: bool,
) -> AdaptiveShadowEvaluation:
    ordered = sorted(candles, key=lambda item: item["timestamp"])
    completed = [
        item for item in ordered
        if datetime.fromisoformat(str(item["timestamp"])).replace(
            second=0, microsecond=0
        ) < as_of.replace(second=0, microsecond=0)
    ]
    today = [
        item for item in completed
        if datetime.fromisoformat(str(item["timestamp"])).date() == as_of.date()
    ]
    reasons: list[str] = []
    zero = ZERO
    if len(today) < 16:
        reasons.append("insufficient_candles")
        return AdaptiveShadowEvaluation(
            str(ranking.get("symbol", "")), False, False, tuple(reasons),
            zero, zero, zero, zero, zero, zero, zero, {},
        )

    latest = D(today[-1].get("closePrice", "0"))
    prior = today[:-1]
    prior_high = max(
        (D(item.get("highPrice", item.get("closePrice", "0"))) for item in prior),
        default=zero,
    )
    breakout_pct = _return(latest, prior_high)
    close_above = latest > prior_high
    hold_count = sum(
        D(item.get("closePrice", "0")) > prior_high
        for item in today[-3:]
    )
    breakout_score = _clamp(
        (breakout_pct / Decimal("0.01")) * Decimal("0.5")
        + (D(hold_count) / Decimal("3")) * Decimal("0.3")
        + (Decimal("0.2") if close_above else zero)
    )
    if not close_above:
        reasons.append("breakout_price_failed")

    volumes = [D(item.get("volume", "0")) for item in today]
    latest_volume = sum(volumes[-5:], zero)
    baseline_blocks = [
        sum(volumes[index - 5:index], zero)
        for index in range(10, len(volumes), 5)
    ]
    baseline = baseline_blocks[:-1] or baseline_blocks
    reference = D(statistics.median(baseline)) if baseline else zero
    volume_ratio = latest_volume / reference if reference > zero else zero
    volume_percentile = _percentile(latest_volume, baseline)
    # The late session prioritizes same-day intraday distribution over a fixed 2x gate.
    volume_score = _clamp(
        (volume_percentile * Decimal("0.65"))
        + (_clamp(volume_ratio / Decimal("2")) * Decimal("0.35"))
    )
    if volume_score < Decimal("0.5"):
        reasons.append("volume_score_failed")

    recent = today[-20:]
    total_volume = sum((D(item.get("volume", "0")) for item in recent), zero)
    vwap = (
        sum(
            (D(item.get("closePrice", "0")) * D(item.get("volume", "0")) for item in recent),
            zero,
        ) / total_volume
        if total_volume > zero else latest
    )
    vwap_distance = _return(latest, vwap)
    vwap_score = _clamp(vwap_distance / Decimal("0.01"))
    if latest <= vwap:
        reasons.append("vwap_failed")

    orderbook = orderbook or {}
    asks = orderbook.get("asks", [])
    bids = orderbook.get("bids", [])
    ask_volume = sum((D(item.get("volume", "0")) for item in asks[:5]), zero)
    bid_volume = sum((D(item.get("volume", "0")) for item in bids[:5]), zero)
    depth = bid_volume + ask_volume
    imbalance = bid_volume / depth if depth > zero else zero
    orderbook_score = _clamp((imbalance - Decimal("0.5")) * Decimal("2"))
    if not asks or not bids:
        reasons.append("orderbook_unavailable")
    elif orderbook_score < Decimal("0.5"):
        reasons.append("bid_imbalance_failed")

    trade_pressure_score = zero
    if trades and asks and bids:
        mid = (D(asks[0]["price"]) + D(bids[0]["price"])) / Decimal("2")
        trade_values = [
            D(item.get("volume", "0"))
            * (Decimal("1") if D(item.get("price", "0")) >= mid else Decimal("-1"))
            for item in trades
        ]
        gross = sum((abs(value) for value in trade_values), zero)
        trade_pressure_score = _clamp(
            (sum(trade_values, zero) / gross + Decimal("1")) / Decimal("2")
            if gross > zero else zero
        )
    if trade_pressure_score < Decimal("0.5"):
        reasons.append("trade_pressure_failed")

    market_context_score = Decimal("1") if market_allowed else zero
    if not market_allowed:
        reasons.append("market_regime_failed")
    entry_score = (
        breakout_score * Decimal("0.25")
        + volume_score * Decimal("0.25")
        + vwap_score * Decimal("0.20")
        + orderbook_score * Decimal("0.15")
        + trade_pressure_score * Decimal("0.10")
        + market_context_score * Decimal("0.05")
    )
    shadow_pass = (
        market_allowed
        and close_above
        and entry_score >= settings.adaptive_shadow_min_score
    )
    if not shadow_pass:
        reasons.append("adaptive_score_failed")
    live_pass = session_breakout_allowed(candles, as_of, as_of.timetz().hour >= 14)
    return AdaptiveShadowEvaluation(
        symbol=str(ranking.get("symbol", "")),
        live_pass=live_pass,
        shadow_pass=shadow_pass,
        rejection_reasons=tuple(dict.fromkeys(reasons)),
        breakout_score=breakout_score,
        volume_score=volume_score,
        vwap_score=vwap_score,
        orderbook_score=orderbook_score,
        trade_pressure_score=trade_pressure_score,
        market_context_score=market_context_score,
        entry_score=entry_score,
        metrics={
            "reference_price": str(latest),
            "breakout_pct": str(breakout_pct),
            "volume_ratio": str(volume_ratio),
            "volume_percentile": str(volume_percentile),
            "vwap_distance": str(vwap_distance),
            "bid_imbalance": str(imbalance),
        },
    )


def exit_reason(
    position: Position,
    current_price: Decimal,
    settings: Settings,
    now: datetime | None = None,
    volatility_rate: Decimal | None = None,
    failure_vwap_count: int = 0,
    failure_breakout_count: int = 0,
    trade_pressure: Decimal | None = None,
    failure_exit_enabled: bool = False,
) -> str | None:
    volatility = volatility_rate or settings.min_volatility_rate
    stop_rate = max(
        settings.stop_loss_rate,
        min(volatility * settings.atr_stop_multiplier, settings.max_stop_loss_rate),
    )
    take_rate = max(
        settings.take_profit_rate,
        volatility * settings.atr_take_profit_multiplier,
    )
    trailing_rate = max(
        settings.trailing_stop_rate,
        volatility * settings.atr_trailing_multiplier,
    )
    activation_rate = max(settings.trailing_stop_rate * Decimal("1.5"), trailing_rate)
    hard_stop = position.entry_price * (Decimal("1") - stop_rate)
    take_profit = position.entry_price * (
        Decimal("1") + take_rate
    )
    trailing_stop = position.high_water_price * (Decimal("1") - trailing_rate)
    trailing_is_armed = (
        position.high_water_price
        >= position.entry_price * (Decimal("1") + activation_rate)
    )
    if current_price <= hard_stop:
        return "hard_stop"
    if now is not None:
        opened_at = datetime.fromisoformat(position.opened_at)
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        if (now - opened_at).total_seconds() < settings.min_hold_seconds:
            return None
    if failure_exit_enabled and now is not None:
        confirmed_vwap = (
            failure_vwap_count >= settings.failure_exit_confirmation_candles
        )
        confirmed_breakout = (
            failure_breakout_count >= settings.failure_exit_confirmation_candles
        )
        selling_pressure = (
            trade_pressure is not None
            and trade_pressure <= settings.failure_exit_max_trade_pressure
        )
        if confirmed_vwap and (selling_pressure or confirmed_breakout):
            return "breakout_failure_vwap"
        if confirmed_breakout and selling_pressure:
            return "breakout_failure_retest"
    if current_price >= take_profit:
        return "take_profit"
    if trailing_is_armed and current_price <= trailing_stop:
        return "trailing_stop"
    return None
