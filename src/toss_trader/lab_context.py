"""Diagnostic-only aligned market context. Never changes order eligibility."""
from datetime import timedelta
from decimal import Decimal as D
from .lab_data import stamp, completed_bars


def market_context(bars, frame):
    unknown = {"status": "unavailable", "shadow_relative_strength": None,
               "shadow_defensive": None}
    try:
        end = stamp(bars[-1]["timestamp"])
        start = end-timedelta(minutes=15)
        def change(rows):
            by_time = {stamp(r["timestamp"]): D(r["closePrice"]) for r in rows}
            # Require every minute, not merely endpoints around a data gap.
            if any(start+timedelta(minutes=i) not in by_time for i in range(16)):
                raise ValueError("context_gap")
            return by_time[end]/by_time[start]-1
        stock = change(bars)
        returns = {}
        for symbol in ("KOSPI", "KOSDAQ"):
            rows = completed_bars(frame["market_bars"][symbol],
                                  stamp(frame["market_observed_at"][symbol]), convention="start")
            returns[symbol] = change(rows)
        weak = all(v < D("-0.001") for v in returns.values())
        strong = all(v > D("0.001") for v in returns.values())
        relative = stock > 0 and stock > max(returns.values())
        return {"status": "available", "at": end.isoformat(), "horizon_minutes": 15,
                "regime": "falling" if weak else "rising" if strong else "mixed",
                "stock_return": str(stock), "index_returns": {k: str(v) for k,v in returns.items()},
                "relative_returns": {k: str(stock-v) for k,v in returns.items()},
                "shadow_relative_strength": relative,
                "shadow_defensive": relative and not weak}
    except (KeyError, IndexError, ValueError, TypeError, ArithmeticError):
        return unknown
