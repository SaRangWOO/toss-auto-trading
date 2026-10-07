"""Independent paper portfolios and a read-only, replayable market-data tape."""
from __future__ import annotations

import argparse
import gzip
import json
import hashlib
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .config import Settings
from .engine import TradingEngine, KST
from .trial_progress import new_progress, completed_days, observe, summary

VARIANTS = ("baseline", "continuation", "retest")
VERSION = 2
READ_METHODS = {"candles", "market_indicator_candles", "prices", "rankings",
                "stocks", "stock_warnings", "trades", "orderbook",
                "price_limits", "kr_market_calendar"}


class MarketTape:
    def __init__(self, client=None, records=None):
        self.client = client
        self.records = records if records is not None else {}
        self.missing = []

    def __getattr__(self, name):
        if name not in READ_METHODS:
            raise RuntimeError(f"Experiment forbids API method: {name}")

        def call(*args, **kwargs):
            key = json.dumps([name, args, kwargs], sort_keys=True)
            if key not in self.records:
                if self.client is None:
                    self.missing.append(key)
                    raise RuntimeError(f"Replay input missing: {name}")
                try:
                    self.records[key] = {"value": getattr(self.client, name)(*args, **kwargs)}
                except Exception as exc:
                    self.records[key] = {"error": type(exc).__name__}
            result = self.records[key]
            if "error" in result:
                raise RuntimeError(f"Market data unavailable: {name}:{result['error']}")
            return deepcopy(result["value"])
        return call


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, default=str, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def safe_settings(settings):
    values = asdict(settings)
    for key in ("client_id", "client_secret", "account_seq", "live_confirmation", "manual_holding_symbols", "project_root"):
        values.pop(key, None)
    return values


def metrics(rows):
    trades = [Decimal(r["closed_pnl"]) for r in rows if r.get("closed_pnl") is not None]
    equities = [Decimal(r["equity"]) for r in rows if r.get("equity") is not None]
    peak = equities[0] if equities else Decimal(0)
    drawdown = Decimal(0)
    for equity in equities:
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    ordered = sorted(trades, reverse=True)
    winners = [pnl for pnl in ordered if pnl > 0]
    daily = {}
    for row in rows:
        if row.get("closed_pnl") is not None:
            day = row["at"][:10]
            daily[day] = daily.get(day, Decimal(0)) + Decimal(row["closed_pnl"])
    net = sum(trades, Decimal(0))
    return {"closed_trades": len(trades), "net_pnl": net,
            "net_per_trade": net / len(trades) if trades else None,
            "max_marked_drawdown_krw": drawdown,
            "net_without_best_one": net - sum(winners[:1], Decimal(0)) if trades else None,
            "net_without_best_two": net - sum(winners[:2], Decimal(0)) if trades else None,
            "daily_net": daily,
            "decision": "reject_if_losses" if trades and net < 0 else "hold_insufficient_evidence",
            "errors": sum(bool(r.get("error")) for r in rows)}


def source_hash():
    digest = hashlib.sha256()
    for name in ("experiment.py", "engine.py", "strategy.py", "state.py", "broker.py", "config.py", "entry_episode.py", "trial_progress.py"):
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


class ParallelPaper(TradingEngine):
    def __init__(self, settings, client):
        if settings.mode != "paper":
            raise ValueError("Parallel experiment requires paper mode")
        super().__init__(settings, client)
        self.source = client
        self.directory = settings.project_root / "reports" / "parallel_paper_v2"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.progress_path = self.directory / "trial_progress.json"
        self.progress = (json.loads(self.progress_path.read_text(encoding="utf-8"))
                         if self.progress_path.exists() else new_progress())
        self._trial_calendar = {}
        source_directory = self.directory / "source" / source_hash()
        source_directory.mkdir(parents=True, exist_ok=True)
        # Archive executable source with every reviewed version for later replay.
        import shutil
        for source in Path(__file__).parent.glob("*.py"):
            if not (source_directory / source.name).exists():
                shutil.copy2(source, source_directory / source.name)
        self.engines = {}
        for variant in VARIANTS:
            root = self.directory / variant
            root.mkdir(parents=True, exist_ok=True)
            config = replace(settings, project_root=root, experiment_variant=variant if variant == "baseline" else variant + "_v2",
                             experiment_version=VERSION, entry_windows=(("10:00", "11:30"),),
                             max_open_positions=1, max_daily_entries=1,
                             live_continuation_entry_enabled=False)
            previous = root / "state" / "paper_portfolio.json"
            if previous.exists():
                cash = Decimal(json.loads(previous.read_text(encoding="utf-8"))["cash"])
                config = replace(config, paper_starting_cash_krw=cash)
            self.engines[variant] = TradingEngine(config, MarketTape(client))
            flow_path = root / "state" / "flow_samples.json"
            if flow_path.exists():
                self.engines[variant]._flow_samples = json.loads(flow_path.read_text(encoding="utf-8"))

    def run_once(self, now=None):
        now = now or datetime.now(KST)
        tape = MarketTape(self.source)
        frame = {"at": now.isoformat(), "schema": VERSION, "source_hash": source_hash(), "variants": {}}
        comparison = {}
        finished = completed_days(self.progress) >= self.progress["target_days"]
        business_day = None
        clock = now.strftime("%H:%M")
        if not finished and "09:00" <= clock <= "15:40":
            day = now.date().isoformat()
            if day not in self._trial_calendar:
                try:
                    today = tape.kr_market_calendar().get("today", {})
                    if today.get("date") == day:
                        regular = (today.get("integrated") or {}).get("regularMarket") or {}
                        self._trial_calendar[day] = bool(regular.get("startTime") and regular.get("endTime"))
                except Exception:
                    self.logger.warning("TRIAL_CALENDAR_UNAVAILABLE")
            business_day = self._trial_calendar.get(day)
        healthy = True
        for variant, engine in self.engines.items():
            engine.settings = replace(engine.settings, entry_windows=
                                      (("10:00", "11:30"),) if not finished and business_day is True else ())
            engine.state.save(engine.settings.state_path)
            initial = json.loads(engine.settings.state_path.read_text(encoding="utf-8"))
            frame["variants"][variant] = {
                "settings": safe_settings(engine.settings), "state": initial,
                "shadow_day": engine._shadow_tracking_day, "shadow": deepcopy(engine._shadow_tracking),
                "flow_samples": deepcopy(engine._flow_samples),
                "confirmations": {k: [t.isoformat(), n] for k, (t, n) in engine._continuation_confirmations.items()}}
            engine.client = tape
            before = engine.state.realized_pnl if engine.state.trading_day == str(now.date()) else Decimal(0)
            held = bool(engine.state.positions)
            error = None
            equity = None
            try:
                engine.run_once(now)
                equity = engine._equity(engine.state.cash, engine._prices_for_positions())
                engine.state.consecutive_errors = 0
            except Exception as exc:
                healthy = False
                error = type(exc).__name__
                engine.state.consecutive_errors += 1
                engine.state.last_error = error
                if engine.state.consecutive_errors >= engine.settings.max_consecutive_errors:
                    engine.state.entries_halted = True
                    engine.state.halt_reason = "experiment_data_errors"
                self.logger.exception("EXPERIMENT_CYCLE_FAILED variant=%s", variant)
            engine.state.save(engine.settings.state_path)
            write_json(engine.settings.project_root / "state" / "flow_samples.json", engine._flow_samples)
            row = {"at": now.isoformat(), "equity": str(equity) if equity is not None else None,
                   "closed_pnl": str(engine.state.realized_pnl - before) if held and not engine.state.positions else None,
                   "entries": engine.state.daily_entries, "positions": len(engine.state.positions), "error": error}
            if row["closed_pnl"] is not None:
                row["closed_positions"] = initial["positions"]
                row["exit_orders"] = [o for o in engine.state.simulated_orders
                                      if o["side"] == "SELL" and o["orderedAt"] == now.isoformat(timespec="seconds")]
            history = engine.settings.project_root / "evaluation.jsonl"
            if not history.exists():
                with history.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"at": now.isoformat(), "equity": initial["cash"],
                                             "closed_pnl": None, "initial": True}) + "\n")
            with history.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row) + "\n")
            rows = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
            comparison[variant] = metrics(rows)
            write_json(engine.settings.project_root / "summary.json", comparison[variant])
        healthy = healthy and not any("error" in record for record in tape.records.values())
        flat = all(not e.state.positions and not e.state.pending_order and not e.state.pending_orders
                   for e in self.engines.values())
        observe(self.progress, now, business_day, healthy and business_day is not None, flat)
        frame["trial"] = summary(self.progress)
        frame["records"] = tape.records
        path = self.directory / "tapes" / str(now.date()) / f"{now:%H%M%S%f}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(frame, stream, default=str)
        write_json(self.progress_path, self.progress)
        write_json(self.directory / "comparison.json", {"updated_at": now.isoformat(),
                   "trial": summary(self.progress), "source_hash": frame["source_hash"], "strategies": comparison})
        # Existing heartbeat, status, and daily-report tools continue to expose
        # the baseline; each trial has its own persistent state and evaluation.
        self.state = self.engines["baseline"].state
        self.state.save(self.settings.state_path)
        self.logger.info("PARALLEL_PAPER_CYCLE at=%s variants=3 tape=%s", now.isoformat(), path.name)


def replay(path, output):
    if output.exists():
        raise ValueError("Replay output must be a new directory")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        frame = json.load(stream)
    if frame["source_hash"] != source_hash():
        raise ValueError("Replay requires the recorded source version")
    tape = MarketTape(records=frame["records"])
    for variant, record in frame["variants"].items():
        root = output / variant
        root.mkdir(parents=True)
        values = record["settings"]
        from typing import get_type_hints
        for key, kind in get_type_hints(Settings).items():
            if key in values and kind is Decimal:
                values[key] = Decimal(values[key])
        config = Settings(**values, project_root=root, client_id="", client_secret="",
                          account_seq=None, live_confirmation="")
        if config.mode != "paper":
            raise ValueError("Replay only supports paper")
        engine = TradingEngine(config, tape)
        write_json(config.state_path, record["state"])
        from .state import PortfolioState
        engine.state = PortfolioState.load_or_fresh(config.state_path, record["state"]["trading_day"], config.paper_starting_cash_krw)
        engine._continuation_confirmations = {k: (datetime.fromisoformat(t), n) for k, (t, n) in record["confirmations"].items()}
        engine._shadow_tracking_day = record["shadow_day"]
        engine._shadow_tracking = record["shadow"]
        engine._flow_samples = record.get("flow_samples", {})
        engine.run_once(datetime.fromisoformat(frame["at"]))


def replay_sequence(paths, output):
    """Carry counterfactual portfolios forward; never restore later real states.

    Missing tape inputs invalidate performance claims even when a strategy catches
    the exception internally. Archive frames are not filled with future prices.
    """
    if output.exists():
        raise ValueError("Replay output must be a new directory")
    engines = {}
    history = {v: [] for v in VARIANTS}
    coverage = []
    last_at = None
    for path in sorted(paths):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            frame = json.load(stream)
        now = datetime.fromisoformat(frame["at"])
        tape = MarketTape(records=frame["records"])
        gap = last_at is not None and now.date() == last_at.date() and (now-last_at).total_seconds() > 90
        for variant in VARIANTS:
            if variant not in engines:
                from typing import get_type_hints
                values = dict(frame["variants"][variant]["settings"])
                for key, kind in get_type_hints(Settings).items():
                    if key in values and kind is Decimal:
                        values[key] = Decimal(values[key])
                values.update(mode="paper", experiment_version=VERSION,
                              experiment_variant=variant if variant == "baseline" else variant + "_v2",
                              entry_windows=(("10:00", "11:30"),), live_continuation_entry_enabled=False)
                config = Settings(**values, project_root=output / variant, client_id="", client_secret="",
                                  account_seq=None, live_confirmation="")
                config.project_root.mkdir(parents=True, exist_ok=True)
                engines[variant] = TradingEngine(config, tape)
                from .state import PortfolioState
                engines[variant].state = PortfolioState.fresh(str(now.date()), config.paper_starting_cash_krw)
            engine = engines[variant]
            engine.client = tape
            held = bool(engine.state.positions)
            before = engine.state.realized_pnl if engine.state.trading_day == str(now.date()) else Decimal(0)
            error = None
            try:
                engine.run_once(now)
                prices = engine._prices_for_positions()
                if set(engine.state.positions) - set(prices):
                    tape.missing.append("position_mark_missing")
                equity = engine._equity(engine.state.cash, prices)
            except Exception as exc:
                error = type(exc).__name__
                equity = None
            history[variant].append({"at": now.isoformat(), "equity": str(equity) if equity is not None else None,
                "closed_pnl": str(engine.state.realized_pnl-before) if held and not engine.state.positions else None,
                "error": error})
            with (engine.settings.project_root / "evaluation.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(history[variant][-1]) + "\n")
            engine.state.save(engine.settings.state_path)
        coverage.append({"at": now.isoformat(), "missing": list(dict.fromkeys(tape.missing)), "gap": gap})
        last_at = now
    valid = bool(coverage) and not any(c["missing"] or c["gap"] for c in coverage) and not any(r["error"] for rows in history.values() for r in rows)
    report = {"source_hash": source_hash(), "sequential": True, "coverage_complete": valid,
              "performance_valid": valid and all(not e.state.positions for e in engines.values()),
              "coverage": coverage, "strategies": {v: metrics(rows) for v, rows in history.items()}}
    if not report["performance_valid"]:
        for result in report["strategies"].values():
            result["decision"] = "invalid_missing_data_or_open_position"
    write_json(output / "comparison.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--sequence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.sequence:
        replay_sequence(args.sequence.rglob("*.json.gz"), args.output)
    elif args.replay:
        replay(args.replay, args.output)
    else:
        parser.error("Provide --replay or --sequence")
