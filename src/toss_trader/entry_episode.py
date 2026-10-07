"""Paper v2: one frozen opening-range reference for age, hold and retest."""
from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from .strategy import (ContinuationEvaluation, completed_intraday_candles, D,
                       adaptive_shadow_evaluate, estimated_trade_pressure)


def evaluate_episode(ranking, candles, orderbook, trades, settings, now, samples):
    raw = adaptive_shadow_evaluate(ranking, candles, orderbook, trades, settings, now, True)
    bars = completed_intraday_candles(candles, now)
    # Duplicate timestamps cannot count as separate completed bars.
    bars = list({b["timestamp"]: b for b in bars}.values())
    reasons = []
    metrics = {}
    opening = [b for b in bars if datetime.fromisoformat(b["timestamp"]).hour == 9
               and datetime.fromisoformat(b["timestamp"]).minute < 30]
    if len(bars) < 16 or not opening:
        return raw, ContinuationEvaluation(False, ("opening_range_unavailable",), metrics), []
    # Fail closed on a truncated opening range rather than silently moving its high.
    if datetime.fromisoformat(opening[0]["timestamp"]).minute != 0 or datetime.fromisoformat(opening[-1]["timestamp"]).minute != 29:
        reasons.append("opening_range_incomplete")
    level = max(D(b.get("highPrice", b["closePrice"])) for b in opening)
    if level <= 0:
        return raw, ContinuationEvaluation(False, ("invalid_reference",), metrics), []
    latest_at = datetime.fromisoformat(bars[-1]["timestamp"])
    if not 0 <= (now - latest_at).total_seconds() <= settings.max_data_age_seconds:
        reasons.append("stale_candles")
    # Current uninterrupted episode; a close at/below the level invalidates it.
    episode = []
    for bar in bars:
        stamp = datetime.fromisoformat(bar["timestamp"])
        if stamp.hour < 9 or (stamp.hour == 9 and stamp.minute < 30):
            continue
        if D(bar["closePrice"]) <= level:
            episode = []
        else:
            episode.append(bar)
    if not episode:
        reasons.append("no_active_breakout")
    age = (now - datetime.fromisoformat(episode[0]["timestamp"])).total_seconds() / 60 if episode else None
    if age is None or not 0 <= age <= settings.continuation_breakout_max_age_minutes:
        reasons.append("breakout_age_failed")
    hold = min(3, len(episode))
    contiguous = len(episode) >= 2 and (datetime.fromisoformat(episode[-1]["timestamp"]) - datetime.fromisoformat(episode[-2]["timestamp"])).total_seconds() == 60
    if not contiguous:
        reasons.append("two_distinct_completed_bars_required")
    distance = D(bars[-1]["closePrice"]) / level - 1
    if not settings.continuation_min_breakout_distance <= distance <= settings.continuation_max_breakout_distance:
        reasons.append("opening_extension_failed")
    if settings.experiment_variant == "retest_v2":
        # Independent progression: breakout -> later touch/hold -> later rebound.
        touch = any(D(b.get("lowPrice", b["closePrice"])) <= level * D("1.003")
                    for b in episode[1:-1][-4:])
        rebound = len(episode) >= 3 and D(episode[-1]["closePrice"]) > D(episode[-2].get("highPrice", episode[-2]["closePrice"]))
        if not touch or not rebound:
            reasons.append("retest_then_rebound_required")
    timestamp = orderbook.get("timestamp")
    try:
        quote_at = datetime.fromisoformat(timestamp)
        quote_fresh = -settings.scan_interval_seconds <= (now - quote_at).total_seconds() <= settings.max_data_age_seconds
    except (TypeError, ValueError):
        quote_fresh = False
    fresh_trades = []
    for trade in trades:
        try:
            age_seconds = (now - datetime.fromisoformat(trade["timestamp"])).total_seconds()
            if -settings.scan_interval_seconds <= age_seconds <= 90:
                fresh_trades.append(trade)
        except (KeyError, TypeError, ValueError):
            pass
    pressure = estimated_trade_pressure(fresh_trades, orderbook)
    samples = [s for s in samples if 0 <= (now - datetime.fromisoformat(s["at"])).total_seconds() <= 90]
    if not quote_fresh or pressure is None:
        samples = []
        reasons.append("flow_data_unavailable_or_stale")
    else:
        # One independent sample per quote timestamp; repeated quotes do not add evidence.
        if not any(s["quote_at"] == timestamp for s in samples):
            samples.append({"at": now.isoformat(), "quote_at": timestamp,
                            "pressure": str(pressure), "book": str(raw.orderbook_score)})
        samples = samples[-3:]
    if len(samples) < 2:
        reasons.append("flow_samples_insufficient")
    mean_pressure = sum((D(s["pressure"]) for s in samples), D(0)) / len(samples) if samples else D(0)
    mean_book = sum((D(s["book"]) for s in samples), D(0)) / len(samples) if samples else D(0)
    breakout = max(D(0), min(D(1), distance / D("0.01") * D("0.5") + D(hold) / 3 * D("0.3") + (D("0.2") if episode else D(0))))
    score = breakout * D("0.25") + raw.volume_score * D("0.25") + raw.vwap_score * D("0.20") + mean_book * D("0.15") + mean_pressure * D("0.10") + raw.market_context_score * D("0.05")
    if score < settings.continuation_min_entry_score:
        reasons.append("entry_score_failed")
    if raw.volume_score < settings.continuation_min_volume_score:
        reasons.append("volume_score_failed")
    if mean_pressure < settings.continuation_min_trade_pressure_score and mean_book < settings.continuation_min_orderbook_score:
        reasons.append("flow_support_failed")
    if not D(0) < D(raw.metrics.get("vwap_distance", 0)) <= settings.continuation_max_vwap_distance:
        reasons.append("vwap_distance_failed")
    metrics.update(reference_kind="opening_range", reference=str(level), breakout_distance=str(distance),
                   breakout_at=episode[0]["timestamp"] if episode else "", breakout_age_minutes=str(age),
                   distinct_hold_bars=str(hold), flow_samples=str(len(samples)),
                   mean_pressure=str(mean_pressure), mean_book=str(mean_book))
    evaluation = replace(raw, breakout_score=breakout, entry_score=score, orderbook_score=mean_book,
                         trade_pressure_score=mean_pressure, shadow_pass=not reasons,
                         rejection_reasons=tuple(reasons),
                         metrics={**raw.metrics, **metrics, "breakout_pct": str(distance),
                                  "legacy_running_high_distance": raw.metrics.get("breakout_pct", "")})
    return evaluation, ContinuationEvaluation(not reasons, tuple(reasons), metrics), samples
