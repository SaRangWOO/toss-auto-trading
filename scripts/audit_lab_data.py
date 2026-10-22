"""Read legacy tapes; verify candle contract and new signal reachability.

No orders, no historical fill claims, no use of missing data. Output stdout only.
"""
import argparse
from collections import Counter
from datetime import datetime
import gzip
import json
from pathlib import Path

from toss_trader.lab_data import completed_bars, opening_range
from toss_trader.lab_strategy import evaluate, STRATEGIES
from toss_trader.paper_lab import default_policy


def audit(directory):
    totals = Counter()
    strategies = {s: Counter() for s in STRATEGIES}
    symbols = set()
    for path in sorted(directory.rglob("*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            frame = json.load(stream)
        now = datetime.fromisoformat(frame["at"])
        if not "09:40" <= now.strftime("%H:%M") <= "11:30":
            continue
        records = frame["records"]
        books = {}
        candles = {}
        for key, value in records.items():
            method, args, kwargs = json.loads(key)
            if "error" in value or not args:
                continue
            if method == "orderbook":
                books[args[0]] = value["value"]
            elif method == "candles":
                candles[args[0]] = value["value"]
        for symbol, rows in candles.items():
            totals["observations"] += 1
            symbols.add(symbol)
            try:
                bars = completed_bars(rows, now)
                totals["opening_complete"] += int(opening_range(bars) is not None)
                for strategy in STRATEGIES:
                    result = evaluate(symbol, bars, books.get(symbol, {}), now, default_policy(), strategy)
                    strategies[strategy][result["status"]] += 1
                    for reason in result["reasons"]:
                        strategies[strategy]["reason:"+reason] += 1
            except (ValueError, KeyError, TypeError, ArithmeticError):
                totals["invalid_data"] += 1
    return {"observations": dict(totals), "unique_symbols": len(symbols),
            "strategies": {s: dict(v) for s, v in strategies.items()},
            "performance_valid": False,
            "limitations": "Legacy selected-universe audit only. Quotes obtained after frame start may be unavailable; no hypothetical fills or return claims."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory), indent=2))
