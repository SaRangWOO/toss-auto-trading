from __future__ import annotations

import csv
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .config import Settings


KST = timezone(timedelta(hours=9))
ZERO = Decimal("0")
VARIANTS = (
    "strict_ohlcv",
    "strict_stock_in_play",
    "retest_stock_in_play",
    "retest_flow_confirmed",
)
HORIZONS = (5, 10, 15, 30)


def D(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class MinuteBar:
    timestamp: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trading_amount: Decimal | None = None
    source: str = "csv"


@dataclass(frozen=True)
class FlowSnapshot:
    timestamp: datetime
    symbol: str
    institution_net_buy: Decimal
    foreign_net_buy: Decimal
    program_net_buy: Decimal
    source: str = "csv"


@dataclass(frozen=True)
class EventFlag:
    timestamp: datetime
    symbol: str


@dataclass(frozen=True)
class ResearchConfig:
    min_trading_amount: Decimal
    min_daily_change: Decimal
    max_daily_change: Decimal
    min_momentum_5m: Decimal
    max_momentum_5m: Decimal
    min_momentum_15m: Decimal
    max_momentum_15m: Decimal
    min_volume_surge: Decimal
    max_vwap_distance: Decimal
    breakout_confirmation_candles: int
    continuation_max_age_minutes: int
    stock_in_play_gap_rate: Decimal
    stock_in_play_opening_rvol: Decimal
    opening_volume_lookback_days: int
    opening_volume_min_days: int
    commission_rate: Decimal
    sell_tax_rate: Decimal
    slippage_bps: Decimal
    morning_start: time = time(10, 0)
    morning_end: time = time(11, 30)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ResearchConfig":
        return cls(
            min_trading_amount=settings.min_trading_amount_krw,
            min_daily_change=settings.min_daily_change_rate,
            max_daily_change=settings.max_daily_change_rate,
            min_momentum_5m=settings.min_5m_momentum_rate,
            max_momentum_5m=settings.max_5m_momentum_rate,
            min_momentum_15m=settings.min_15m_momentum_rate,
            max_momentum_15m=settings.max_15m_momentum_rate,
            min_volume_surge=settings.min_volume_surge,
            max_vwap_distance=settings.max_price_over_vwap_rate,
            breakout_confirmation_candles=settings.breakout_confirmation_candles,
            continuation_max_age_minutes=(
                settings.continuation_breakout_max_age_minutes
            ),
            stock_in_play_gap_rate=Decimal("0.02"),
            stock_in_play_opening_rvol=Decimal("2.0"),
            opening_volume_lookback_days=20,
            opening_volume_min_days=5,
            commission_rate=settings.paper_commission_rate,
            sell_tax_rate=settings.paper_sell_tax_rate,
            slippage_bps=settings.paper_slippage_bps,
        )

    @property
    def round_trip_cost_rate(self) -> Decimal:
        return (
            self.commission_rate * Decimal("2")
            + self.sell_tax_rate
            + self.slippage_bps * Decimal("2") / Decimal("10000")
        )


@dataclass(frozen=True)
class ResearchTrade:
    variant: str
    symbol: str
    signal_at: datetime
    entry_at: datetime
    entry_price: Decimal
    opening_high: Decimal
    gap_rate: Decimal
    opening_rvol: Decimal | None
    cumulative_trading_amount: Decimal
    flow_confirmed: bool
    return_5m: Decimal | None
    return_10m: Decimal | None
    return_15m: Decimal | None
    return_30m: Decimal | None
    mfe_30m: Decimal | None
    mae_30m: Decimal | None
    round_trip_cost_rate: Decimal


@dataclass(frozen=True)
class ResearchResult:
    trades: tuple[ResearchTrade, ...]
    summaries: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


def _aware_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def _required_columns(path: Path, names: set[str], fieldnames: list[str] | None) -> None:
    available = set(fieldnames or [])
    missing = names - available
    if missing:
        raise ValueError(f"{path} missing columns: {', '.join(sorted(missing))}")


def load_minute_bars(path: Path) -> list[MinuteBar]:
    if not path.exists():
        raise ValueError(f"minute-bar CSV does not exist: {path}")
    bars: dict[tuple[str, datetime], MinuteBar] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _required_columns(
            path,
            {"timestamp", "symbol", "open", "high", "low", "close", "volume"},
            reader.fieldnames,
        )
        for line_number, row in enumerate(reader, start=2):
            try:
                timestamp = _aware_timestamp(row["timestamp"], field="timestamp")
                symbol = row["symbol"].strip()
                bar = MinuteBar(
                    timestamp=timestamp,
                    symbol=symbol,
                    open=D(row["open"]),
                    high=D(row["high"]),
                    low=D(row["low"]),
                    close=D(row["close"]),
                    volume=D(row["volume"]),
                    trading_amount=(
                        D(row["trading_amount"])
                        if row.get("trading_amount", "").strip()
                        else None
                    ),
                    source=row.get("source", "csv").strip() or "csv",
                )
            except (KeyError, ValueError, ArithmeticError) as exc:
                raise ValueError(f"invalid minute-bar row {line_number}") from exc
            if not symbol or min(bar.open, bar.high, bar.low, bar.close) <= ZERO:
                raise ValueError(f"invalid price or symbol at minute-bar row {line_number}")
            if bar.volume < ZERO:
                raise ValueError(f"negative volume at minute-bar row {line_number}")
            bars[(symbol, timestamp)] = bar
    if not bars:
        raise ValueError("minute-bar CSV is empty")
    return sorted(bars.values(), key=lambda item: (item.timestamp, item.symbol))


def load_flow_snapshots(path: Path | None) -> list[FlowSnapshot]:
    if path is None:
        return []
    if not path.exists():
        raise ValueError(f"flow CSV does not exist: {path}")
    snapshots: dict[tuple[str, datetime], FlowSnapshot] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _required_columns(
            path,
            {
                "timestamp",
                "symbol",
                "institution_net_buy",
                "foreign_net_buy",
                "program_net_buy",
            },
            reader.fieldnames,
        )
        for line_number, row in enumerate(reader, start=2):
            try:
                timestamp = _aware_timestamp(row["timestamp"], field="timestamp")
                symbol = row["symbol"].strip()
                snapshot = FlowSnapshot(
                    timestamp=timestamp,
                    symbol=symbol,
                    institution_net_buy=D(row["institution_net_buy"]),
                    foreign_net_buy=D(row["foreign_net_buy"]),
                    program_net_buy=D(row["program_net_buy"]),
                    source=row.get("source", "csv").strip() or "csv",
                )
            except (KeyError, ValueError, ArithmeticError) as exc:
                raise ValueError(f"invalid flow row {line_number}") from exc
            if not symbol:
                raise ValueError(f"missing symbol at flow row {line_number}")
            snapshots[(symbol, timestamp)] = snapshot
    return sorted(snapshots.values(), key=lambda item: (item.timestamp, item.symbol))


def load_event_flags(path: Path | None) -> list[EventFlag]:
    if path is None:
        return []
    if not path.exists():
        raise ValueError(f"event CSV does not exist: {path}")
    events: dict[tuple[str, datetime], EventFlag] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _required_columns(
            path, {"timestamp", "symbol", "news_flag"}, reader.fieldnames
        )
        for line_number, row in enumerate(reader, start=2):
            value = row["news_flag"].strip().lower()
            if value not in {"0", "1", "false", "true", "no", "yes"}:
                raise ValueError(f"invalid news_flag at event row {line_number}")
            if value in {"1", "true", "yes"}:
                try:
                    timestamp = _aware_timestamp(
                        row["timestamp"], field="event timestamp"
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"invalid timestamp at event row {line_number}"
                    ) from exc
                symbol = row["symbol"].strip()
                if not symbol:
                    raise ValueError(f"missing symbol at event row {line_number}")
                events[(symbol, timestamp)] = EventFlag(timestamp, symbol)
    return sorted(events.values(), key=lambda item: (item.timestamp, item.symbol))


def _return(current: Decimal, previous: Decimal) -> Decimal:
    return current / previous - Decimal("1") if previous > ZERO else ZERO


def _median(values: Iterable[Decimal]) -> Decimal | None:
    items = list(values)
    return D(statistics.median(items)) if items else None


def _in_morning_window(value: datetime, config: ResearchConfig) -> bool:
    observed = value.timetz().replace(tzinfo=None)
    return config.morning_start <= observed <= config.morning_end


def _strict_breakout(
    bars: list[MinuteBar], index: int, opening_high: Decimal, confirmation: int
) -> bool:
    if index - confirmation < 0:
        return False
    confirmed = bars[index - confirmation + 1 : index + 1]
    previous = bars[index - confirmation]
    return (
        len(confirmed) == confirmation
        and all(item.close > opening_high for item in confirmed)
        and previous.close <= opening_high
    )


def _retest_breakout(
    bars: list[MinuteBar],
    index: int,
    opening_high: Decimal,
    config: ResearchConfig,
) -> bool:
    if index < 2 or not all(item.close > opening_high for item in bars[index - 1 : index + 1]):
        return False
    breakout_index: int | None = None
    for candidate in range(1, index + 1):
        if (
            bars[candidate].timestamp.time() >= config.morning_start
            and bars[candidate - 1].close <= opening_high
            and bars[candidate].close > opening_high
        ):
            breakout_index = candidate
    if breakout_index is None:
        return False
    age = bars[index].timestamp - bars[breakout_index].timestamp
    if age < timedelta(0) or age > timedelta(minutes=config.continuation_max_age_minutes):
        return False
    retest_ceiling = opening_high * Decimal("1.002")
    return any(
        item.low <= retest_ceiling and item.close > opening_high
        for item in bars[breakout_index : index + 1]
    )


def _latest_flow(
    snapshots: list[FlowSnapshot], symbol: str, as_of: datetime
) -> FlowSnapshot | None:
    eligible = [
        item
        for item in snapshots
        if item.symbol == symbol
        and item.timestamp.date() == as_of.date()
        and item.timestamp <= as_of
        and as_of - item.timestamp <= timedelta(hours=2)
    ]
    return max(eligible, key=lambda item: item.timestamp) if eligible else None


def _flow_confirmed(snapshot: FlowSnapshot | None) -> bool:
    if snapshot is None:
        return False
    return snapshot.institution_net_buy > ZERO and (
        snapshot.foreign_net_buy > ZERO or snapshot.program_net_buy > ZERO
    )


def _outcomes(
    bars: list[MinuteBar],
    entry_index: int,
    cost_rate: Decimal,
) -> tuple[dict[int, Decimal | None], Decimal | None, Decimal | None]:
    entry = bars[entry_index]
    returns: dict[int, Decimal | None] = {}
    for horizon in HORIZONS:
        target = entry.timestamp + timedelta(minutes=horizon)
        future = next((item for item in bars[entry_index:] if item.timestamp >= target), None)
        returns[horizon] = (
            _return(future.close, entry.open) - cost_rate if future is not None else None
        )
    end = entry.timestamp + timedelta(minutes=30)
    path = [
        item
        for item in bars[entry_index:]
        if entry.timestamp <= item.timestamp <= end
    ]
    if not path:
        return returns, None, None
    mfe = max(_return(item.high, entry.open) for item in path) - cost_rate
    mae = min(_return(item.low, entry.open) for item in path) - cost_rate
    return returns, mfe, mae


def evaluate_research(
    bars: list[MinuteBar],
    config: ResearchConfig,
    *,
    flows: list[FlowSnapshot] | None = None,
    events: list[EventFlag] | None = None,
    split_date: date | None = None,
) -> ResearchResult:
    flows = flows or []
    events = events or []
    grouped: dict[tuple[str, date], list[MinuteBar]] = {}
    for bar in bars:
        if bar.symbol.upper() in {"KOSPI", "KOSDAQ"}:
            continue
        grouped.setdefault((bar.symbol, bar.timestamp.date()), []).append(bar)
    for values in grouped.values():
        values.sort(key=lambda item: item.timestamp)

    days_by_symbol: dict[str, list[date]] = {}
    for symbol, trading_day in grouped:
        days_by_symbol.setdefault(symbol, []).append(trading_day)
    for values in days_by_symbol.values():
        values.sort()

    opening_volumes: dict[tuple[str, date], Decimal] = {}
    for key, day_bars in grouped.items():
        opening_volumes[key] = sum(
            (
                item.volume
                for item in day_bars
                if time(9, 0) <= item.timestamp.time() < time(9, 30)
            ),
            ZERO,
        )

    trades: list[ResearchTrade] = []
    for symbol, days in sorted(days_by_symbol.items()):
        prior_close: Decimal | None = None
        opening_history: list[Decimal] = []
        for trading_day in days:
            day_bars = grouped[(symbol, trading_day)]
            opening = [
                item
                for item in day_bars
                if time(9, 0) <= item.timestamp.time() < time(9, 30)
            ]
            if prior_close is None:
                prior_close = day_bars[-1].close
                opening_history.append(opening_volumes[(symbol, trading_day)])
                continue
            if not opening:
                prior_close = day_bars[-1].close
                opening_history.append(opening_volumes[(symbol, trading_day)])
                continue
            opening_high = max(item.high for item in opening)
            baseline = opening_history[-config.opening_volume_lookback_days :]
            baseline_median = _median(value for value in baseline if value > ZERO)
            opening_rvol = (
                opening_volumes[(symbol, trading_day)] / baseline_median
                if baseline_median is not None
                and baseline_median > ZERO
                and len([value for value in baseline if value > ZERO])
                >= config.opening_volume_min_days
                else None
            )
            gap_rate = _return(opening[0].open, prior_close)
            signaled: set[str] = set()
            cumulative_amount = ZERO
            for index, bar in enumerate(day_bars[:-1]):
                estimated_amount = bar.close * bar.volume
                cumulative_amount += estimated_amount
                if bar.trading_amount is not None and bar.trading_amount > ZERO:
                    cumulative_amount = bar.trading_amount
                signal_at = bar.timestamp + timedelta(minutes=1)
                if not _in_morning_window(signal_at, config) or index < 15:
                    continue
                daily_change = _return(bar.close, prior_close)
                momentum_5m = _return(bar.close, day_bars[index - 5].close)
                momentum_15m = _return(bar.close, day_bars[index - 15].close)
                reference_volume = _median(
                    item.volume for item in day_bars[max(0, index - 10) : index]
                )
                volume_surge = (
                    bar.volume / reference_volume
                    if reference_volume is not None and reference_volume > ZERO
                    else ZERO
                )
                recent = day_bars[max(0, index - 19) : index + 1]
                recent_volume = sum((item.volume for item in recent), ZERO)
                vwap = (
                    sum((item.close * item.volume for item in recent), ZERO)
                    / recent_volume
                    if recent_volume > ZERO
                    else bar.close
                )
                vwap_distance = _return(bar.close, vwap)
                base_pass = (
                    cumulative_amount >= config.min_trading_amount
                    and config.min_daily_change <= daily_change <= config.max_daily_change
                    and config.min_momentum_5m
                    <= momentum_5m
                    <= config.max_momentum_5m
                    and config.min_momentum_15m
                    <= momentum_15m
                    <= config.max_momentum_15m
                    and volume_surge >= config.min_volume_surge
                    and ZERO < vwap_distance <= config.max_vwap_distance
                )
                if not base_pass:
                    continue
                known_event = any(
                    item.symbol == symbol
                    and item.timestamp.date() == trading_day
                    and item.timestamp <= signal_at
                    for item in events
                )
                stock_in_play = (
                    abs(gap_rate) >= config.stock_in_play_gap_rate
                    or (
                        opening_rvol is not None
                        and opening_rvol >= config.stock_in_play_opening_rvol
                    )
                    or known_event
                )
                strict = _strict_breakout(
                    day_bars,
                    index,
                    opening_high,
                    config.breakout_confirmation_candles,
                )
                retest = _retest_breakout(day_bars, index, opening_high, config)
                snapshot = _latest_flow(flows, symbol, signal_at)
                confirmed_flow = _flow_confirmed(snapshot)
                candidates = {
                    "strict_ohlcv": strict,
                    "strict_stock_in_play": strict and stock_in_play,
                    "retest_stock_in_play": retest and stock_in_play,
                    "retest_flow_confirmed": (
                        retest and stock_in_play and confirmed_flow
                    ),
                }
                for variant, allowed in candidates.items():
                    if not allowed or variant in signaled:
                        continue
                    entry_index = index + 1
                    returns, mfe, mae = _outcomes(
                        day_bars,
                        entry_index,
                        config.round_trip_cost_rate,
                    )
                    entry = day_bars[entry_index]
                    trades.append(
                        ResearchTrade(
                            variant=variant,
                            symbol=symbol,
                            signal_at=signal_at,
                            entry_at=entry.timestamp,
                            entry_price=entry.open,
                            opening_high=opening_high,
                            gap_rate=gap_rate,
                            opening_rvol=opening_rvol,
                            cumulative_trading_amount=cumulative_amount,
                            flow_confirmed=confirmed_flow,
                            return_5m=returns[5],
                            return_10m=returns[10],
                            return_15m=returns[15],
                            return_30m=returns[30],
                            mfe_30m=mfe,
                            mae_30m=mae,
                            round_trip_cost_rate=config.round_trip_cost_rate,
                        )
                    )
                    signaled.add(variant)
            prior_close = day_bars[-1].close
            opening_history.append(opening_volumes[(symbol, trading_day)])

    all_dates = sorted({bar.timestamp.date() for bar in bars})
    chosen_split = split_date or _automatic_split(all_dates)
    summaries = _summaries(trades, chosen_split)
    metadata = {
        "bar_count": len(bars),
        "symbol_count": len({bar.symbol for bar in bars}),
        "date_count": len(all_dates),
        "first_date": all_dates[0].isoformat() if all_dates else None,
        "last_date": all_dates[-1].isoformat() if all_dates else None,
        "split_date": chosen_split.isoformat() if chosen_split else None,
        "flow_snapshot_count": len(flows),
        "event_count": len(events),
        "orderbook_coverage": False,
        "trade_tick_coverage": False,
        "round_trip_cost_rate": str(config.round_trip_cost_rate),
        "promotion_blocked": True,
        "promotion_reason": (
            "Historical OHLCV research cannot validate live orderbook, trade ticks, "
            "latency, or account execution. Results may nominate a paper experiment only."
        ),
    }
    return ResearchResult(
        trades=tuple(sorted(trades, key=lambda item: (item.entry_at, item.variant))),
        summaries=tuple(summaries),
        metadata=metadata,
    )


def _automatic_split(all_dates: list[date]) -> date | None:
    if len(all_dates) < 2:
        return None
    index = min(len(all_dates) - 1, max(1, int(len(all_dates) * 0.7)))
    return all_dates[index]


def _mean(values: list[Decimal]) -> Decimal | None:
    return sum(values, ZERO) / D(len(values)) if values else None


def _profit_factor(values: list[Decimal]) -> Decimal | None:
    gains = sum((value for value in values if value > ZERO), ZERO)
    losses = abs(sum((value for value in values if value < ZERO), ZERO))
    if losses == ZERO:
        return None if gains == ZERO else Decimal("999")
    return gains / losses


def _max_drawdown(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    cumulative = ZERO
    peak = ZERO
    drawdown = ZERO
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    return drawdown


def _summaries(
    trades: list[ResearchTrade], split_date: date | None
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for segment in ("all", "development", "evaluation"):
        for variant in VARIANTS:
            selected = [item for item in trades if item.variant == variant]
            if segment == "development" and split_date is not None:
                selected = [item for item in selected if item.entry_at.date() < split_date]
            elif segment == "evaluation" and split_date is not None:
                selected = [item for item in selected if item.entry_at.date() >= split_date]
            elif segment != "all" and split_date is None:
                selected = []
            returns_30 = [
                item.return_30m for item in selected if item.return_30m is not None
            ]
            returns_15 = [
                item.return_15m for item in selected if item.return_15m is not None
            ]
            mfes = [item.mfe_30m for item in selected if item.mfe_30m is not None]
            maes = [item.mae_30m for item in selected if item.mae_30m is not None]
            win_rate = (
                D(sum(value > ZERO for value in returns_30)) / D(len(returns_30))
                if returns_30
                else None
            )
            average_30 = _mean(returns_30)
            profit_factor = _profit_factor(returns_30)
            candidate = (
                segment == "evaluation"
                and len(returns_30) >= 30
                and average_30 is not None
                and average_30 > ZERO
                and profit_factor is not None
                and profit_factor > Decimal("1.2")
            )
            summaries.append(
                {
                    "segment": segment,
                    "variant": variant,
                    "trades": len(selected),
                    "complete_30m": len(returns_30),
                    "win_rate_30m": win_rate,
                    "average_return_15m": _mean(returns_15),
                    "average_return_30m": average_30,
                    "average_mfe_30m": _mean(mfes),
                    "average_mae_30m": _mean(maes),
                    "profit_factor_30m": profit_factor,
                    "max_drawdown_30m": _max_drawdown(returns_30),
                    "paper_candidate": candidate,
                }
            )
    return summaries


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def write_research_report(result: ResearchResult, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "research-summary.json"
    markdown_path = output_dir / "research-summary.md"
    payload = {
        "metadata": result.metadata,
        "summaries": list(result.summaries),
        "trades": [asdict(item) for item in result.trades],
    }
    json_path.write_text(
        json.dumps(_json_value(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(result), encoding="utf-8")
    return markdown_path, json_path


def _percent(value: Any) -> str:
    if value is None:
        return "-"
    return f"{D(value) * Decimal('100'):.3f}%"


def _render_markdown(result: ResearchResult) -> str:
    metadata = result.metadata
    lines = [
        "# External research replay",
        "",
        "## Data coverage",
        "",
        f"- Bars: {metadata['bar_count']}",
        f"- Symbols: {metadata['symbol_count']}",
        f"- Dates: {metadata['first_date']} ~ {metadata['last_date']} "
        f"({metadata['date_count']} days)",
        f"- Evaluation split: {metadata['split_date'] or 'unavailable'}",
        f"- Flow snapshots: {metadata['flow_snapshot_count']}",
        f"- Modeled round-trip cost: {_percent(metadata['round_trip_cost_rate'])}",
        "",
        "## Variant comparison",
        "",
        "| Segment | Variant | Trades | Win 30m | Avg 15m | Avg 30m | "
        "MFE 30m | MAE 30m | PF 30m | Paper candidate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in result.summaries:
        pf = item["profit_factor_30m"]
        pf_text = f"{D(pf):.3f}" if pf is not None else "-"
        candidate_text = "yes" if item["paper_candidate"] else "no"
        lines.append(
            f"| {item['segment']} | {item['variant']} | {item['trades']} | "
            f"{_percent(item['win_rate_30m'])} | "
            f"{_percent(item['average_return_15m'])} | "
            f"{_percent(item['average_return_30m'])} | "
            f"{_percent(item['average_mfe_30m'])} | "
            f"{_percent(item['average_mae_30m'])} | "
            f"{pf_text} | {candidate_text} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- `strict_ohlcv` approximates the current price/volume gates but does not "
            "reconstruct historical order books or trade ticks.",
            "- `strict_stock_in_play` adds a 2% gap, 2x opening relative volume, or a "
            "supplied news/event flag.",
            "- `retest_stock_in_play` requires a recent opening-range breakout, retest, "
            "and two completed closes above the range.",
            "- `retest_flow_confirmed` additionally requires positive institutional flow "
            "and positive foreign or program flow from a supplied snapshot.",
            f"- Live promotion is blocked: {metadata['promotion_reason']}",
            "",
        ]
    )
    return "\n".join(lines)
