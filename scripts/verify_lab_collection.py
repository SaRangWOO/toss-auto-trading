"""Read-only integration check. Never calls PaperLab.apply or an order API."""
from collections import Counter
from pathlib import Path
import json
import tempfile
from toss_trader.cli import _client
from toss_trader.config import Settings
from toss_trader.lab_data import completed_bars, opening_range, stamp, quote
from toss_trader.lab_strategy import evaluate, STRATEGIES
from toss_trader.paper_lab import PaperLab


def main():
    settings = Settings.from_project(Path.cwd())
    if settings.mode != "paper":
        raise ValueError("Read-only lab check requires paper configuration")
    with tempfile.TemporaryDirectory(prefix="toss-lab-readonly-") as temporary:
        lab = PaperLab(settings, _client(settings), output=Path(temporary))
        frame = lab.collect()
        quality = Counter()
        reasons = Counter()
        quote_errors = Counter()
        quote_ages = []
        for symbol in frame["universe"]:
            try:
                rows = completed_bars(frame["bars"][symbol], stamp(frame["bar_observed_at"][symbol]))
                quality["opening_complete"] += int(opening_range(rows) is not None)
                try:
                    quote_ages.append((stamp(frame["at"])-stamp(frame["books"][symbol]["timestamp"])).total_seconds())
                    quote(frame["books"].get(symbol, {}), stamp(frame["at"]))
                except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                    quote_errors[type(exc).__name__+":"+str(exc)] += 1
                for strategy in STRATEGIES:
                    result = evaluate(symbol, rows, frame["books"].get(symbol, {}), stamp(frame["at"]), lab.policy, strategy)
                    quality[strategy+":"+result["status"]] += 1
                    reasons.update(result["reasons"])
            except (KeyError, ValueError, TypeError, ArithmeticError):
                quality["invalid_data"] += 1
        print(json.dumps({"at": frame["at"], "symbols": len(frame["universe"]),
                          "collection_errors": frame["errors"], "quality": dict(quality),
                          "reasons": dict(reasons), "orders": "not_called",
                          "quote_errors": dict(quote_errors),
                          "quote_age_seconds": {"min": min(quote_ages) if quote_ages else None,
                                                "max": max(quote_ages) if quote_ages else None},
                          "ledger_apply": "not_called"}, indent=2))


if __name__ == "__main__":
    main()
