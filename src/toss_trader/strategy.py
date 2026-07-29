from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
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


def _return(current: Decimal, previous: Decimal) -> Decimal:
    if previous <= 0:
        return ZERO
    return (current / previous) - Decimal("1")


def analyze_candidate(
    ranking: dict[str, Any],
    candles: list[dict[str, Any]],
    orderbook: dict[str, Any],
    settings: Settings,
) -> MomentumSignal | None:
    if len(candles) < 16:
        return None
    ordered_all = sorted(candles, key=lambda item: item["timestamp"])
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
    )


def position_quantity(
    *,
    cash: Decimal,
    equity: Decimal,
    price: Decimal,
    settings: Settings,
) -> int:
    if cash <= 0 or equity <= 0 or price <= 0:
        return 0
    risk_limited = (
        equity * settings.risk_per_trade_rate / settings.stop_loss_rate
    )
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


def exit_reason(
    position: Position,
    current_price: Decimal,
    settings: Settings,
) -> str | None:
    hard_stop = position.entry_price * (Decimal("1") - settings.stop_loss_rate)
    take_profit = position.entry_price * (
        Decimal("1") + settings.take_profit_rate
    )
    trailing_stop = position.high_water_price * (
        Decimal("1") - settings.trailing_stop_rate
    )
    trailing_is_armed = (
        position.high_water_price
        >= position.entry_price * (Decimal("1") + settings.trailing_stop_rate)
    )
    if current_price <= hard_stop:
        return "hard_stop"
    if current_price >= take_profit:
        return "take_profit"
    if trailing_is_armed and current_price <= trailing_stop:
        return "trailing_stop"
    return None
