"""Small, explicit hypotheses; no institutional-flow proxy hard gates."""
from decimal import Decimal as D
from statistics import median
from .lab_data import stamp, consecutive, opening_range, quote

STRATEGIES = ("opening_control", "pullback", "range_breakout")


def evaluate(symbol, bars, book, now, policy, strategy):
    if strategy not in STRATEGIES:
        raise ValueError("unknown_strategy")
    result = {"symbol": symbol, "strategy": strategy, "status": "unavailable",
              "reasons": [], "gates": {}, "metrics": {}}
    if len(bars) < 31 or not consecutive(bars[-31:]):
        result["reasons"] = ["recent_bars_missing_or_gapped"]
        return result
    if not 0 <= (stamp(now) - stamp(bars[-1]["timestamp"])).total_seconds() <= 90:
        result["reasons"] = ["stale_bars"]
        return result
    try:
        bid, ask, bid_size, ask_size = quote(book, now)
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        result["reasons"] = [str(exc) if type(exc) is ValueError else "quote_unavailable"]
        return result
    closes = [D(b["closePrice"]) for b in bars]
    latest = closes[-1]
    prior = bars[-16:-1]
    ranges = [max(D(b["highPrice"]) - D(b["lowPrice"]),
                  abs(D(b["highPrice"]) - closes[i-1]),
                  abs(D(b["lowPrice"]) - closes[i-1]))
              for i, b in enumerate(bars) if i >= len(bars)-14]
    atr = sum(ranges) / D(len(ranges))
    if atr <= 0:
        result["reasons"] = ["zero_volatility"]
        return result
    med_volume = D(str(median(D(b["volume"]) for b in prior)))
    relative_volume = D(bars[-1]["volume"]) / med_volume if med_volume else D(0)
    recent_turnover = sum(D(b["closePrice"])*D(b["volume"]) for b in bars[-5:])
    spread = (ask-bid)/ask
    trend = sum(closes[-6:-1])/5 > sum(closes[-26:-6])/20
    if strategy == "opening_control":
        opening = opening_range(bars)
        if opening is None:
            result["reasons"] = ["opening_range_unavailable"]
            return result
        reference = D(opening["high"])
        structure = closes[-2] <= reference < latest
        stop = reference - atr
        anchor = bars[0]["timestamp"]
    elif strategy == "range_breakout":
        base = bars[-11:-1]
        reference = max(D(b["highPrice"]) for b in base)
        floor = min(D(b["lowPrice"]) for b in base)
        structure = (reference-floor <= D(policy["range_width_atr"])*atr and
                     closes[-2] <= reference < latest)
        stop = floor - atr*D("0.25")
        anchor = base[0]["timestamp"]
    else:
        pull = bars[-4:-1]
        reference = D(pull[-1]["highPrice"])
        floor = min(D(b["lowPrice"]) for b in pull)
        pre_high = max(D(b["highPrice"]) for b in bars[-11:-4])
        depth = pre_high-floor
        structure = (trend and D("0.5")*atr <= depth <= D("3")*atr and
                     any(D(b["closePrice"]) < D(b["openPrice"]) for b in pull) and
                     latest > reference and latest > D(bars[-1]["openPrice"]))
        stop = floor - atr*D("0.25")
        anchor = pull[0]["timestamp"]
    risk = ask-stop
    cost = ask * (2*D(policy["slippage_bps"])/10000 + 2*D(policy["commission_rate"]) + D(policy["sell_tax_rate"])) + ask-bid
    gates = {
        "structure": bool(structure),
        "volume": relative_volume >= D(policy["min_relative_volume"]),
        "spread": spread <= D(policy["max_spread_rate"]),
        "liquidity": recent_turnover >= D(policy["min_recent_turnover"]),
        "extension": D(0) < ask-reference <= D(policy["max_extension_atr"])*atr,
        "risk_distance": stop > 0 and D(0) < risk/ask <= D(policy["max_stop_rate"]),
        # This is a price-space feasibility test, NOT estimated expected profit.
        "cost_space": 2*atr >= D(policy["cost_space_multiple"])*cost,
    }
    result.update(status="eligible" if all(gates.values()) else "rejected", gates=gates,
                  reasons=[k for k, passed in gates.items() if not passed],
                  event_id=f"{strategy}:{symbol}:{anchor}", bar_at=bars[-1]["timestamp"],
                  stop=str(stop), atr=str(atr), ask=str(ask), bid=str(bid),
                  ask_size=str(ask_size), bid_size=str(bid_size), reference=str(reference),
                  metrics={"relative_volume": str(relative_volume), "recent_turnover": str(recent_turnover),
                           "spread": str(spread), "cost_per_share": str(cost), "trend_up": trend,
                           "price_space_to_cost": str(2*atr/cost),
                           "baseline_cost_space_pass": 2*atr >= D("3")*cost})
    return result
