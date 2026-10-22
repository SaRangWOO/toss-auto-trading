"""Explicit timestamp contracts for the paper lab, independent of live code.

Toss Candle.timestamp is END time; MarketIndicatorCandle.timestamp is START.
Source: https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
KST = timezone(timedelta(hours=9))


def stamp(value):
    result = datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("naive_timestamp")
    return result.astimezone(KST)


def completed_bars(rows, now, *, convention="end"):
    if convention not in {"start", "end"}:
        raise ValueError("unknown_candle_timestamp_contract")
    now = stamp(now)
    bars = {}
    for row in rows:
        end = stamp(row["timestamp"])
        if convention == "start":
            end += timedelta(minutes=1)
        if end.second or end.microsecond:
            raise ValueError("unaligned_minute")
        if end > now or end.date() != now.date():
            continue
        # KRX regular-session bars only; exclude premarket and previous day.
        start = end - timedelta(minutes=1)
        if start.strftime("%H:%M") < "09:00" or end.strftime("%H:%M") > "15:30":
            continue
        values = {k: Decimal(str(row[k])) for k in
                  ("openPrice", "highPrice", "lowPrice", "closePrice", "volume")}
        if not all(x.is_finite() for x in values.values()):
            raise ValueError("nonfinite_bar")
        o, h, l, c, v = (values[k] for k in values)
        if min(o, h, l, c) <= 0 or v < 0 or not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("invalid_ohlcv")
        normalized = {**{k: str(v) for k, v in values.items()}, "timestamp": end.isoformat()}
        if end in bars and bars[end] != normalized:
            raise ValueError("conflicting_duplicate_bar")
        bars[end] = normalized
    return [bars[t] for t in sorted(bars)]


def consecutive(bars):
    return all((stamp(b["timestamp"]) - stamp(a["timestamp"])).total_seconds() == 60
               for a, b in zip(bars, bars[1:]))


def opening_range(bars):
    opening = [b for b in bars if "09:01" <= stamp(b["timestamp"]).strftime("%H:%M") <= "09:30"]
    if len(opening) != 30 or not consecutive(opening):
        return None
    return {"high": str(max(Decimal(b["highPrice"]) for b in opening)),
            "low": str(min(Decimal(b["lowPrice"]) for b in opening))}


def merge_completed(previous, incoming, now):
    # Completed historical bars are immutable within a session. An API revision
    # is an explicit data-quality error, not a silently moving reference.
    return completed_bars([*previous, *incoming], now)


def quote(book, now, max_age=90):
    age = (stamp(now) - stamp(book["timestamp"])).total_seconds()
    if age < 0:
        raise ValueError("future_quote_clock_check_required")
    if age > max_age:
        raise ValueError("stale_quote")
    def levels(side):
        result = [(Decimal(str(x["price"])), Decimal(str(x["volume"]))) for x in book[side]]
        if not result or any(not p.is_finite() or not v.is_finite() or p <= 0 or v <= 0 for p, v in result):
            raise ValueError("invalid_book")
        return result
    ask, ask_size = min(levels("asks"))
    bid, bid_size = max(levels("bids"))
    if bid >= ask:
        raise ValueError("locked_or_crossed_book")
    return bid, ask, bid_size, ask_size
