"""Offline descriptive audit; never calls an API or changes strategy state."""
import gzip
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = root / "reports/parallel_paper_v1"
rows = []
for path in sorted((base / "baseline/reports/filter_funnel").glob("*.jsonl")):
    rows.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
morning = [r for r in rows if r.get("continuation")]
counts = Counter()
single = Counter()
neighbors = []
groups = defaultdict(list)
for r in morning:
    groups[(r["timestamp"][:10], r["symbol"])].append(r)
    reasons = r["continuation"]["rejection_reasons"]
    counts.update(reasons)
    if len(reasons) == 1:
        single.update(reasons)
for key, values in groups.items():
    for i, r in enumerate(values):
        if r["continuation"]["eligible"]:
            neighbors.append({"day_symbol": key, "samples": [
                {"at": x["timestamp"], "score": x["scores"]["entry"],
                 "breakout": x["metrics"]["breakout_pct"],
                 "opening_distance": float(x["metrics"]["reference_price"]) / float(x["continuation"]["metrics"]["opening_high"]) - 1,
                 "reasons": x["continuation"]["rejection_reasons"]}
                for x in values[max(0, i-1):i+2]]})
tape_stats = Counter()
recomputed = Counter()
for directory in sorted((base / "tapes").iterdir()):
    for path in sorted(directory.glob("*.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            frame = json.load(stream)
        at = datetime.fromisoformat(frame["at"])
        if not (10 <= at.hour < 12):
            continue
        records = [(json.loads(k), v.get("value")) for k, v in frame["records"].items() if "value" in v]
        ranks = next((v for (name, args, kwargs), v in records if name == "rankings"), [])
        tape_stats["cycles_with_rankings"] += bool(ranks)
        candles = {args[0]: v for (name, args, kwargs), v in records if name == "candles"}
        books = {args[0] for (name, args, kwargs), v in records if name == "orderbook"}
        for rank in ranks:
            symbol = rank["symbol"]
            if symbol not in books:
                continue
            tape_stats["book_evaluations"] += 1
            amount = float(rank["tradingAmount"])
            tape_stats["below_500eok"] += amount < 50000000000
            bars = [b for b in candles.get(symbol, []) if datetime.fromisoformat(b["timestamp"]).date() == at.date()
                    and datetime.fromisoformat(b["timestamp"]).replace(second=0, microsecond=0) < at.replace(second=0, microsecond=0)]
            bars.sort(key=lambda b: b["timestamp"])
            if len(bars) < 16:
                continue
            prior_high = max(float(b.get("highPrice", b["closePrice"])) for b in bars[:-1])
            hold = sum(float(b["closePrice"]) > prior_high for b in bars[-3:])
            recomputed["samples"] += 1
            recomputed[f"hold_count_{hold}"] += 1
            opening = [b for b in bars if datetime.fromisoformat(b["timestamp"]).hour == 9
                       and datetime.fromisoformat(b["timestamp"]).minute < 30]
            if opening:
                level = max(float(b.get("highPrice", b["closePrice"])) for b in opening)
                latest = float(bars[-1]["closePrice"])
                if .005 <= latest / level - 1 <= .02:
                    recomputed["opening_distance_in_bounds"] += 1
                    recomputed["opening_in_bounds_but_moving_reference_fails"] += not (.005 <= latest / prior_high - 1 <= .02)

result = {"scope": "Recorded cycles only; repeated samples, not independent trades. No P&L inference.",
          "funnel_rows": len(rows), "morning_rows": len(morning), "reason_counts": counts,
          "only_one_reason": single, "eligible_neighbors": neighbors,
          "tape_stats": tape_stats, "recomputed": recomputed}
print(json.dumps(result, ensure_ascii=False, indent=2))
