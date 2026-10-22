"""Opt-in, read-only-market-data paper laboratory. No broker/order methods.

One immutable policy per output directory. Raw frames precede ledger updates;
replay carries state forward rather than restoring actual recorded portfolios.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
import gzip
import hashlib
import json
import time

from .engine import KST, _is_leveraged_or_inverse_etp
from .experiment import MarketTape, safe_settings, write_json
from .lab_data import stamp, merge_completed, completed_bars, opening_range, quote
from .lab_strategy import STRATEGIES, evaluate
from .lab_context import market_context
from .trial_progress import new_progress, observe, summary


def default_policy():
    return json.loads((Path(__file__).parents[2] / "config" / "paper_lab_v3.json").read_text(encoding="utf-8"))


def validate_policy(p):
    required = set(default_policy())
    if set(p) != required or p["schema"] != 3:
        raise ValueError("lab_policy_schema_mismatch")
    for key in required - {"schema", "entry_windows", "force_exit_time", "stop_time"}:
        value = D(str(p[key]))
        if not value.is_finite() or value < 0:
            raise ValueError(f"invalid_lab_policy:{key}")
    for key in ("candidate_limit", "max_daily_entries", "cooldown_minutes", "time_exit_minutes"):
        if not isinstance(p[key], int) or p[key] <= 0:
            raise ValueError(f"invalid_lab_integer:{key}")
    if p["candidate_limit"] > 30 or not 0 < D(p["risk_per_trade"]) <= D("0.01"):
        raise ValueError("unsafe_lab_risk_or_universe")
    for key in ("daily_loss_rate", "max_stop_rate", "participation_rate", "book_participation_rate"):
        if not 0 < D(p[key]) <= 1:
            raise ValueError(f"invalid_lab_fraction:{key}")
    for key in ("execution_cash", "research_cash", "execution_max_trade", "research_max_trade"):
        if D(p[key]) <= 0:
            raise ValueError(f"invalid_lab_budget:{key}")
    if not 0 < D(p["research_daily_loss_krw"]) <= D(p["research_cash"])*D("0.01"):
        raise ValueError("invalid_research_daily_loss_krw")
    if D(p["slippage_bps"]) > 500 or D(p["commission_rate"])+D(p["sell_tax_rate"]) >= D("0.1"):
        raise ValueError("invalid_lab_costs")
    def clock(value):
        return datetime.strptime(value, "%H:%M").time()
    for start, end in p["entry_windows"]:
        if not clock("09:00") <= clock(start) < clock(end) < clock(p["force_exit_time"]) <= clock("15:30"):
            raise ValueError("invalid_lab_window")
    if not p["entry_windows"] or clock(p["stop_time"]) < clock("15:40"):
        raise ValueError("invalid_lab_stop")


def code_hash():
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(source.read_bytes())
    return digest.hexdigest()


def fresh_state(policy):
    accounts = {}
    for strategy in STRATEGIES:
        for profile in ("research", "execution"):
            cash = policy[f"{profile}_cash"]
            accounts[f"{strategy}/{profile}"] = {"cash": cash, "initial": cash,
                "day": "", "day_equity": cash, "entries": 0, "halted": False,
                "position": None, "trades": [], "last_entry": {}, "peak": cash,
                "drawdown": "0", "last_equity": cash}
    return {"schema": 3, "last_at": None, "day": "", "bars": {}, "accounts": accounts,
            "episodes": {}, "outcomes": [], "diagnostics": {}, "coverage": {},
            "progress": new_progress(), "errors": 0, "consecutive_errors": 0,
            "entry_halt": False}


def quantity(cash, equity, ask, stop, recent_turnover, ask_size, cap, policy, *, remaining_loss=None, bid=None):
    slip = D(policy["slippage_bps"])/10000
    fee, tax = D(policy["commission_rate"]), D(policy["sell_tax_rate"])
    entry = ask*(1+slip)*(1+fee)
    loss = entry-stop*(1-slip)*(1-fee-tax)
    if stop <= 0 or stop >= ask or loss <= 0:
        return 0
    # Cover both the planned stop and immediate liquidation, including costs.
    if bid is not None:
        loss = max(loss, entry-bid*(1-slip)*(1-fee-tax))
    budget = equity*D(policy["risk_per_trade"])
    if remaining_loss is not None:
        budget = min(budget, max(D(0), remaining_loss))
    return max(0, min(int(cash//entry), int(cap//entry),
        int(budget//loss),
        int((recent_turnover*D(policy["participation_rate"]))//entry),
        int(ask_size*D(policy["book_participation_rate"]))))


class PaperLab:
    def __init__(self, settings, client, *, output=None, policy=None, replay=False):
        if settings.mode != "paper":
            raise ValueError("Paper lab forbids live mode")
        self.settings, self.source = settings, client
        self.policy = deepcopy(policy or default_policy())
        # Never expand execution-account risk beyond the current operating caps.
        for key, value in (("risk_per_trade", settings.risk_per_trade_rate),
                           ("daily_loss_rate", settings.max_daily_loss_rate),
                           ("execution_max_trade", settings.max_trade_krw),
                           ("max_spread_rate", settings.max_spread_rate)):
            self.policy[key] = str(min(D(self.policy[key]), value))
        for key, value in (("slippage_bps", settings.paper_slippage_bps),
                           ("commission_rate", settings.paper_commission_rate),
                           ("sell_tax_rate", settings.paper_sell_tax_rate)):
            self.policy[key] = str(max(D(self.policy[key]), value))
        validate_policy(self.policy)
        self.root = output or settings.project_root / "reports" / "paper_lab_v3"
        self.root.mkdir(parents=True, exist_ok=True)
        self.manifest = {"source_hash": code_hash(), "policy": self.policy,
                         "max_daily_loss_krw": str(settings.max_daily_loss_krw),
                         "max_position_rate": str(settings.max_position_rate),
                         "execution_max_daily_entries": settings.max_daily_entries,
                         "max_daily_profit_lock_rate": str(settings.max_daily_profit_lock_rate),
                         "max_consecutive_errors": settings.max_consecutive_errors,
                         "replay": replay}
        manifest_path = self.root / "manifest.json"
        if manifest_path.exists() and json.loads(manifest_path.read_text(encoding="utf-8")) != self.manifest:
            raise ValueError("lab_version_changed_use_new_output_directory")
        write_json(manifest_path, self.manifest)
        import shutil
        archive = self.root / "source" / self.manifest["source_hash"]
        archive.mkdir(parents=True, exist_ok=True)
        for source in Path(__file__).parent.glob("*.py"):
            if not (archive / source.name).exists():
                shutil.copy2(source, archive / source.name)
        write_json(archive / "policy.json", self.policy)
        self.path = self.root / "ledger.json"
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else fresh_state(self.policy)
        if self.state.get("schema") != 3:
            raise ValueError("invalid_lab_ledger")

    def collect(self):
        # Whitelisted MarketTape is the only API surface accessible here.
        tape = MarketTape(self.source)
        frame = {"schema": 3, "candle_contract": "toss_end_1m", "source_hash": code_hash(),
                 "settings": safe_settings(self.settings), "policy": self.policy,
                 "universe": [], "instruments": {}, "bars": {}, "bar_observed_at": {},
                 "books": {}, "warnings": {}, "errors": []}
        now = datetime.now(KST)
        try:
            today = tape.kr_market_calendar().get("today", {})
            frame["business_day"] = (today.get("date") == str(now.date()) and
                bool(((today.get("integrated") or {}).get("regularMarket") or {}).get("startTime")) and
                bool(((today.get("integrated") or {}).get("regularMarket") or {}).get("endTime")))
            if today.get("date") != str(now.date()):
                frame["errors"].append("calendar_date_mismatch")
            if frame["business_day"] and "09:00" <= now.strftime("%H:%M") <= self.policy["stop_time"]:
                frame.update(market_bars={}, market_observed_at={}, context_errors=[])
                for index in ("KOSPI", "KOSDAQ"):
                    try:
                        frame["market_observed_at"][index] = datetime.now(KST).isoformat()
                        frame["market_bars"][index] = tape.market_indicator_candles(index, count=40)
                    except Exception:
                        # Optional research input: never substitute zero or halt baseline.
                        frame["context_errors"].append("index_unavailable:"+index)
                rankings = tape.rankings(self.settings.ranking_count)
                frame["ranking_count"] = len(rankings)
                # No affordability or absolute daily turnover filter before research.
                selected = [str(r["symbol"]) for r in rankings][:self.policy["candidate_limit"]]
                frame["universe"] = list(dict.fromkeys(selected))
                needed = set(selected)
                needed.update(a["position"]["symbol"] for a in self.state["accounts"].values() if a["position"])
                needed.update(e["symbol"] for e in self.state["outcomes"] if not e["complete"])
                frame["instruments"] = {str(r["symbol"]): r for r in tape.stocks(sorted(needed))}
                for symbol in sorted(needed):
                    try:
                        frame["bar_observed_at"][symbol] = datetime.now(KST).isoformat()
                        frame["bars"][symbol] = tape.candles(symbol, count=200)
                        cached = self.state["bars"].get(symbol, []) if self.state["day"] == str(now.date()) else []
                        if now.strftime("%H:%M") >= "09:30" and opening_range(cached) is None:
                            # An afternoon newcomer must not lose its morning
                            # reference just because the latest-200 window slid.
                            observed = stamp(frame["bar_observed_at"][symbol])
                            if opening_range(completed_bars(frame["bars"][symbol], observed)) is None:
                                before = now.replace(hour=9, minute=30, second=0, microsecond=0).isoformat()
                                frame["bars"][symbol].extend(tape.candles(symbol, count=30, before=before))
                        frame["books"][symbol] = tape.orderbook(symbol)
                        frame["warnings"][symbol] = tape.stock_warnings(symbol)
                    except Exception:
                        frame["errors"].append(f"market_data:{symbol}")
        except Exception:
            frame["errors"].append("collection_failed")
            frame.setdefault("business_day", False)
        frame["at"] = datetime.now(KST).isoformat()
        frame["records"] = tape.records
        return frame

    def daily_loss_limit(self, account, profile):
        limit = D(account["day_equity"])*D(self.policy["daily_loss_rate"])
        absolute = (D(self.policy["research_daily_loss_krw"]) if profile == "research"
                    else self.settings.max_daily_loss_krw)
        return min(limit, absolute) if absolute > 0 else limit

    def _exit_and_mark(self, account, books, now, profile="execution"):
        p = account["position"]
        if not p:
            return D(account["cash"]), True
        try:
            bid, _, bid_size, _ = quote(books[p["symbol"]], now)
        except (KeyError, ValueError, TypeError, ArithmeticError):
            return D(account["last_equity"]), False
        p["high"] = str(max(D(p["high"]), bid))
        reason = None
        if stamp(p["opened_at"]).date() != now.date():
            reason = "overnight_recovery"
        elif now.strftime("%H:%M") >= self.policy["force_exit_time"]:
            reason = "session_exit"
        elif bid <= D(p["stop"]):
            reason = "structural_stop"
        else:
            bars = self.state["bars"].get(p["symbol"], [])
            if bars and bars[-1]["timestamp"] != p.get("last_exit_bar"):
                p["last_exit_bar"] = bars[-1]["timestamp"]
                close = D(bars[-1]["closePrice"])
                if D(p["high"]) >= D(p["entry"])+D(p["risk"]) and close <= D(p["high"])-2*D(p["atr"]):
                    reason = "completed_bar_trailing"
            if (now-stamp(p["opened_at"])).total_seconds() >= self.policy["time_exit_minutes"]*60 and bid <= D(p["entry"])+D(p["risk"])*D("0.5"):
                reason = reason or "no_progress_timeout"
        unit = bid*(1-D(self.policy["slippage_bps"])/10000)*(1-D(self.policy["commission_rate"])-D(self.policy["sell_tax_rate"]))
        equity = D(account["cash"])+unit*p["quantity"]
        day_loss = D(account["day_equity"])-equity
        limit = self.daily_loss_limit(account, profile)
        if day_loss >= limit:
            reason = "daily_loss_guard"
            account["halted"] = True
        if reason:
            # Do not claim a fill beyond observable bid size. Keep unresolved risk
            # in the ledger and block new entries; no imaginary forced liquidation.
            if bid_size < p["quantity"]:
                account["halted"] = True
                return equity, False
            net = unit*p["quantity"]-D(p["entry_cost"])
            account["cash"] = str(equity)
            slip = D(self.policy["slippage_bps"])/10000
            fee, tax = D(self.policy["commission_rate"]), D(self.policy["sell_tax_rate"])
            stress_net = (bid*(1-2*slip)*(1-2*fee-2*tax)-D(p["entry_ask"])*(1+2*slip)*(1+2*fee))*p["quantity"]
            account["trades"].append({**p, "exit_at": now.isoformat(), "exit": str(bid),
                "reason": reason, "net": str(net), "stress_net": str(stress_net),
                "hold_seconds": (now-stamp(p["opened_at"])).total_seconds()})
            account["position"] = None
        return equity, True

    def _outcomes(self, frame, now):
        for event in self.state["outcomes"]:
            if event["complete"]:
                continue
            elapsed = (now-stamp(event["at"])).total_seconds()
            if elapsed < 0:
                continue
            try:
                bid, _, _, _ = quote(frame["books"][event["symbol"]], now)
                value = bid/D(event["ask"])-1
                event["mfe"] = str(max(D(event["mfe"]), value))
                event["mae"] = str(min(D(event["mae"]), value))
            except (KeyError, ValueError, TypeError, ArithmeticError):
                value = None
            for minute in (5, 10, 15, 30):
                key = str(minute)
                if elapsed >= minute*60 and key not in event["returns"]:
                    # Never substitute a much later quote for a missed checkpoint.
                    event["returns"][key] = (str(value-D(event["cost_rate"]))
                        if value is not None and elapsed <= minute*60+90 else None)
            if elapsed >= 30*60:
                event["complete"] = True

    def apply(self, frame):
        if frame.get("schema") != 3 or frame.get("candle_contract") != "toss_end_1m":
            raise ValueError("unsupported_lab_frame")
        if frame.get("policy") != self.policy:
            raise ValueError("frame_policy_mismatch")
        now = stamp(frame["at"])
        if self.state["entry_halt"] and not self.state.get("entry_halt_reason"):
            self.state["entry_halt_reason"] = "unknown"
        if self.state["last_at"] and now <= stamp(self.state["last_at"]):
            raise ValueError("duplicate_or_reversed_frame")
        healthy = not frame["errors"]
        health_reasons = list(frame["errors"])
        if self.state["last_at"] and now.date() == stamp(self.state["last_at"]).date() and (now-stamp(self.state["last_at"])).total_seconds() > 90:
            healthy = False
            health_reasons.append("cycle_gap")
        day = str(now.date())
        if self.state["day"] != day:
            self.state["day"], self.state["bars"], self.state["episodes"] = day, {}, {}
            self.state["recovery_cycles"] = 0
        coverage = self.state["coverage"].setdefault(day, {"evaluations": 0, "available": 0,
            "eligible": 0, "unique_episodes": 0, "data_errors": 0, "gate_failures": {}, "single_gate_blocks": {}})
        for symbol, incoming in frame["bars"].items():
            try:
                observed = stamp(frame["bar_observed_at"][symbol])
                if observed > now:
                    raise ValueError("future_collection_time")
                incoming = completed_bars(incoming, observed)
                self.state["bars"][symbol] = merge_completed(self.state["bars"].get(symbol, []), incoming, now)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                coverage["data_errors"] += 1
                self.state["bars"].pop(symbol, None)
        finished = summary(self.state["progress"])["status"] == "complete"
        window = any(start <= now.strftime("%H:%M") < end for start, end in self.policy["entry_windows"])
        decisions = []
        if frame["business_day"] and window and not finished:
            for symbol in frame["universe"]:
                instrument = frame["instruments"].get(symbol)
                if (instrument is None or not isinstance(frame["warnings"].get(symbol), list)
                        or frame["warnings"][symbol] or _is_leveraged_or_inverse_etp(instrument)):
                    decisions.append({"symbol": symbol, "status": "safety_block", "reasons": ["instrument_or_warning"]})
                    continue
                for strategy in STRATEGIES:
                    decision = evaluate(symbol, self.state["bars"].get(symbol, []), frame["books"].get(symbol, {}), now, self.policy, strategy)
                    decision["market_context"] = market_context(self.state["bars"].get(symbol, []), frame)
                    context_counts = coverage.setdefault("market_context", {"available": 0, "unavailable": 0})
                    context_counts[decision["market_context"]["status"]] += 1
                    decisions.append(decision)
                    coverage["evaluations"] += 1
                    if decision["status"] == "unavailable":
                        coverage["data_errors"] += 1
                        continue
                    coverage["available"] += 1
                    coverage["eligible"] += int(decision["status"] == "eligible")
                    for gate in decision["reasons"]:
                        key = strategy+":"+gate
                        coverage["gate_failures"][key] = coverage["gate_failures"].get(key, 0)+1
                    if len(decision["reasons"]) == 1:
                        key = strategy+":"+decision["reasons"][0]
                        coverage["single_gate_blocks"][key] = coverage["single_gate_blocks"].get(key, 0)+1
                    episode_key = strategy+":"+symbol
                    if not decision["gates"]["structure"]:
                        self.state["episodes"].pop(episode_key, None)
                    elif episode_key not in self.state["episodes"]:
                        self.state["episodes"][episode_key] = decision["event_id"]
                        coverage["unique_episodes"] += 1
                        self.state["outcomes"].append({"id": decision["event_id"], "symbol": symbol,
                            "strategy": strategy, "at": now.isoformat(), "ask": decision["ask"],
                            "market_context": decision["market_context"],
                            "reasons": decision["reasons"], "returns": {}, "mfe": "0", "mae": "0",
                            # bid/ask spread already included in forward bid/ask return.
                            "cost_rate": str(2*D(self.policy["slippage_bps"])/10000+2*D(self.policy["commission_rate"])+D(self.policy["sell_tax_rate"])),
                            "complete": False})
        self._outcomes(frame, now)
        marks = {name: self._exit_and_mark(account, frame["books"], now, name.split("/")[1])
                 for name, account in self.state["accounts"].items()}
        healthy = healthy and all(ok for _, ok in marks.values())
        for name, (_, ok) in marks.items():
            if not ok:
                position = self.state["accounts"][name]["position"]
                reason = "insufficient_bid_depth"
                try:
                    quote(frame["books"].get(position["symbol"], {}), now)
                except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                    reason = str(exc) if type(exc) is ValueError else "quote_unavailable"
                health_reasons.append("held_market_data:"+name+":"+reason)
        for name, account in self.state["accounts"].items():
            strategy, profile = name.split("/")
            equity, mark_ok = marks[name]
            account["mark_valid"] = mark_ok
            if account["day"] != day:
                account.update(day=day, day_equity=str(equity), entries=0, halted=False)
                if account["position"]:
                    account["halted"] = True
            account["last_equity"] = str(equity)
            account["peak"] = str(max(D(account["peak"]), equity))
            account["drawdown"] = str(max(D(account["drawdown"]), D(account["peak"])-equity))
            limit = self.daily_loss_limit(account, profile)
            if D(account["day_equity"])-equity >= limit:
                account["halted"] = True
            if self.settings.max_daily_profit_lock_rate > 0 and equity >= D(account["day_equity"])*(1+self.settings.max_daily_profit_lock_rate):
                account["halted"] = True
            if (account["position"] or account["halted"] or self.state["entry_halt"] or
                    not healthy or not window or finished or not frame["business_day"] or
                    account["entries"] >= (min(self.policy["max_daily_entries"], self.settings.max_daily_entries)
                                           if profile == "execution" else self.policy["max_daily_entries"])):
                continue
            eligible = [d for d in decisions if d.get("strategy") == strategy and d["status"] == "eligible"]
            eligible.sort(key=lambda d: (-D(d["metrics"]["relative_volume"]), d["symbol"]))
            for d in eligible:
                last = account["last_entry"].get(d["symbol"])
                if last and (now-stamp(last)).total_seconds() < self.policy["cooldown_minutes"]*60:
                    continue
                ask, stop = D(d["ask"]), D(d["stop"])
                cap = D(self.policy[f"{profile}_max_trade"])
                if profile == "execution":
                    cap = min(cap, equity*self.settings.max_position_rate)
                q = quantity(D(account["cash"]), equity, ask, stop, D(d["metrics"]["recent_turnover"]),
                             D(d["ask_size"]), cap, self.policy,
                             remaining_loss=limit-max(D(0), D(account["day_equity"])-equity),
                             bid=D(d["bid"]))
                if q == 0:
                    key = name+":budget_or_risk_or_depth"
                    self.state["diagnostics"][key] = self.state["diagnostics"].get(key, 0)+1
                    continue
                entry = ask*(1+D(self.policy["slippage_bps"])/10000)
                cost = entry*q*(1+D(self.policy["commission_rate"]))
                account["cash"] = str(D(account["cash"])-cost)
                account["entries"] += 1
                account["last_entry"][d["symbol"]] = now.isoformat()
                account["position"] = {"symbol": d["symbol"], "quantity": q, "entry": str(entry), "entry_ask": str(ask),
                    "entry_cost": str(cost), "stop": str(stop), "risk": str(entry-stop), "atr": d["atr"],
                    "high": str(entry), "opened_at": now.isoformat(), "event_id": d["event_id"]}
                account["position"]["market_context"] = d["market_context"]
                marked = D(account["cash"])+D(d["bid"])*q*(1-D(self.policy["slippage_bps"])/10000)*(1-D(self.policy["commission_rate"])-D(self.policy["sell_tax_rate"]))
                account["last_equity"] = str(marked)
                account["drawdown"] = str(max(D(account["drawdown"]), D(account["peak"])-marked))
                break
        self.state["errors"] += int(not healthy)
        self.state["consecutive_errors"] = 0 if healthy else self.state["consecutive_errors"]+1
        if not healthy:
            kind = "held_market_data" if health_reasons and all(r.startswith("held_market_data:") for r in health_reasons) else "infrastructure"
            if self.state["consecutive_errors"] == 1:
                self.state["error_streak_kind"] = kind
            elif kind != "held_market_data":
                self.state["error_streak_kind"] = "infrastructure"
            self.state.setdefault("health_events", []).append({"at": now.isoformat(), "reasons": health_reasons})
        if self.state["consecutive_errors"] >= self.settings.max_consecutive_errors:
            self.state["entry_halt"] = True
            if self.state.get("entry_halt_reason") not in {"infrastructure", "manual", "unknown"}:
                self.state["entry_halt_reason"] = self.state.get("error_streak_kind", "unknown")
        assessed = [d for d in decisions if d.get("strategy") in STRATEGIES]
        coverage_ok = (not window or not frame["business_day"] or finished or
                       bool(assessed) and sum(d["status"] != "unavailable" for d in assessed)/len(assessed) >= 0.8)
        recovery_ok = (healthy and coverage_ok and window and frame["business_day"] and not finished
                       and bool(assessed) and all(not a["position"] for a in self.state["accounts"].values()))
        if self.state["entry_halt"] and self.state.get("entry_halt_reason") == "held_market_data":
            self.state["recovery_cycles"] = self.state.get("recovery_cycles", 0)+1 if recovery_ok else 0
            if self.state["recovery_cycles"] >= 5:
                self.state["entry_halt"] = False
                self.state.setdefault("health_events", []).append({"at": now.isoformat(), "reasons": ["recovered_flat_after_5_healthy_cycles"]})
                self.state["entry_halt_reason"] = None
                self.state["recovery_cycles"] = 0
        else:
            self.state["recovery_cycles"] = 0
        observe(self.state["progress"], now, frame["business_day"], healthy and coverage_ok,
                all(not a["position"] for a in self.state["accounts"].values()))
        self.state["last_at"] = now.isoformat()
        with (self.root / "decisions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"at": frame["at"], "decisions": decisions})+"\n")
        write_json(self.path, self.state)
        write_json(self.root / "comparison.json", self.report())

    def report(self):
        accounts = {}
        for name, a in self.state["accounts"].items():
            trades = a["trades"]
            net = sum((D(t["net"]) for t in trades), D(0))
            winners = sorted((D(t["net"]) for t in trades if D(t["net"]) > 0), reverse=True)
            daily = {}
            for t in trades:
                day = t["exit_at"][:10]
                daily[day] = daily.get(day, D(0))+D(t["net"])
            accounts[name] = {"closed_trades": len(trades), "net_pnl": str(net),
                "net_per_trade": str(net/len(trades)) if trades else None,
                "net_without_best_one": str(net-sum(winners[:1], D(0))) if trades else None,
                "net_without_best_two": str(net-sum(winners[:2], D(0))) if trades else None,
                "cost_stress_net": str(sum((D(t["stress_net"]) for t in trades), D(0))),
                "max_marked_drawdown": a["drawdown"], "daily_net": {d: str(v) for d, v in daily.items()},
                "open_position": a["position"] is not None,
                "mark_valid": a.get("mark_valid", True),
                "decision": "reject_if_losses" if net < 0 else "hold_unvalidated"}
            baseline = self.state.get("policy_baseline_trade_counts", {}).get(name, 0)
            accounts[name]["current_policy_closed_trades"] = len(trades[baseline:])
            accounts[name]["current_policy_net_pnl"] = str(sum((D(t["net"]) for t in trades[baseline:]), D(0)))
        return {"updated_at": self.state["last_at"], "mode": "paper_only", "source_hash": code_hash(),
                "policy_transitions": self.state.get("policy_transitions", []),
                "trial": summary(self.state["progress"]), "coverage": self.state["coverage"],
                "entry_halt": self.state["entry_halt"], "errors": self.state["errors"],
                "entry_halt_reason": self.state.get("entry_halt_reason"),
                "recovery_cycles": self.state.get("recovery_cycles", 0),
                "recent_health_events": self.state.get("health_events", [])[-20:],
                "accounts": accounts, "diagnostics": self.state["diagnostics"],
                "cash_benchmark_net": "0",
                "outcome_summary": self.outcome_summary(),
                "market_shadow_summary": self.market_shadow_summary(),
                "marks_are_sampled_not_tick_extrema": True,
                "no_automatic_live_promotion": True}

    def market_shadow_summary(self):
        groups = {}
        for event in self.state["outcomes"]:
            if event["reasons"]:
                continue
            context = event.get("market_context", {})
            if context.get("status") != "available":
                continue
            for variant, keep in (("baseline", True), ("relative_strength", context["shadow_relative_strength"]),
                                  ("defensive", context["shadow_defensive"])):
                key = event["strategy"]+":"+variant
                group = groups.setdefault(key, {"eligible_episodes": 0, "selected": 0, "returns": {}})
                group["eligible_episodes"] += 1
                group["selected"] += int(keep)
                if keep:
                    for minute, value in event["returns"].items():
                        if value is not None:
                            group["returns"].setdefault(minute, []).append(D(value))
        for group in groups.values():
            group["returns"] = {m: {"count": len(v), "mean_net_return": str(sum(v)/len(v))}
                                for m,v in group["returns"].items()}
        return {"diagnostic_only_not_portfolio_pnl": True, "groups": groups}

    def outcome_summary(self):
        groups = {}
        for event in self.state["outcomes"]:
            # Gate ablation is diagnostic: only one failed gate is isolated.
            # It is not a tradable portfolio return or an out-of-sample result.
            label = "accepted" if not event["reasons"] else (
                "without_"+event["reasons"][0] if len(event["reasons"]) == 1 else "multiple_blocks")
            key = event["strategy"]+":"+label
            g = groups.setdefault(key, {"episodes": 0, "complete": 0, "returns": {}})
            g["episodes"] += 1
            g["complete"] += int(event["complete"])
            for minute, value in event["returns"].items():
                if value is not None:
                    g["returns"].setdefault(minute, []).append(D(value))
        for g in groups.values():
            g["returns"] = {m: {"count": len(v), "mean_net_return": str(sum(v)/len(v))}
                            for m, v in g["returns"].items()}
        return groups

    def run_once(self):
        frame = self.collect()
        now = stamp(frame["at"])
        path = self.root / "tapes" / str(now.date()) / f"{now:%H%M%S%f}.json.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(frame, stream, default=str)
        self.apply(frame)
        return self.report()

    def run_forever(self):
        while True:
            started = time.monotonic()
            self.run_once()
            write_json(self.root / "heartbeat.json", {"updated_at": datetime.now(KST).isoformat()})
            if datetime.now(KST).strftime("%H:%M") >= self.policy["stop_time"]:
                return
            time.sleep(max(1, self.settings.scan_interval_seconds-(time.monotonic()-started)))


def migrate_flat_risk_policy(settings, previous, output, *, same_policy=False, reviewed_data_halt=False):
    """Explicit offline migration. Caller must stop the runner; never resets risk state."""
    previous, output = Path(previous), Path(output)
    if output.exists() or previous.resolve() == output.resolve():
        raise ValueError("migration_requires_new_output")
    state = json.loads((previous / "ledger.json").read_text(encoding="utf-8"))
    old = json.loads((previous / "manifest.json").read_text(encoding="utf-8"))
    if any(a["position"] is not None for a in state["accounts"].values()):
        raise ValueError("migration_requires_flat_accounts")
    policy = default_policy()
    expected = policy if same_policy else {k: v for k, v in policy.items() if k != "research_daily_loss_krw"}
    if expected != old["policy"]:
        raise ValueError("migration_requires_only_research_limit_change")
    lab = PaperLab(settings, object(), output=output)
    effective = lab.policy if same_policy else {k: v for k, v in lab.policy.items() if k != "research_daily_loss_krw"}
    if effective != old["policy"]:
        raise ValueError("migration_effective_policy_mismatch")
    for key in ("max_daily_loss_krw", "max_position_rate", "execution_max_daily_entries",
                "max_daily_profit_lock_rate", "max_consecutive_errors"):
        if lab.manifest[key] != old[key]:
            raise ValueError("migration_settings_mismatch")
    if not same_policy:
        state["policy_baseline_trade_counts"] = {n: len(a["trades"]) for n, a in state["accounts"].items()}
    if reviewed_data_halt and state["entry_halt"]:
        if not same_policy or state.get("entry_halt_reason") not in (None, "held_market_data"):
            raise ValueError("reviewed_halt_migration_not_allowed")
        state["entry_halt_reason"] = "held_market_data"
        state["recovery_cycles"] = 0
    state.setdefault("policy_transitions", []).append({
        "at": datetime.now(KST).isoformat(), "previous_output": str(previous.resolve()),
        "previous_source_hash": old["source_hash"], "new_source_hash": lab.manifest["source_hash"],
        "change": "market_context_and_guarded_data_recovery" if same_policy else "research_daily_loss_10000_and_remaining_budget_sizing",
        "reviewed_data_halt": reviewed_data_halt,
        "balances_losses_halts_and_progress_preserved": True})
    lab.state = state
    write_json(lab.path, state)
    write_json(lab.root / "comparison.json", lab.report())
    return lab.report()


def write_lab_report(project_root):
    """Snapshot the atomic comparison without API calls or ledger mutation."""
    root = project_root / "reports" / "paper_lab_v3"
    comparison = json.loads((root / "comparison.json").read_text(encoding="utf-8"))
    day = stamp(comparison["updated_at"]).date().isoformat()
    path = root / "daily" / f"{day}.json"
    write_json(path, comparison)
    return path


def replay_frames(settings, paths, output):
    if output.exists():
        raise ValueError("Replay output must be a new directory")
    lab = None
    for path in sorted(paths):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            frame = json.load(stream)
        if frame.get("source_hash") != code_hash():
            raise ValueError("Replay requires the recorded source version")
        if lab is None:
            from typing import get_type_hints
            from .config import Settings
            # Replay the recorded cost/risk settings, not today's local .env.
            values = dict(frame["settings"])
            if values.get("mode") != "paper":
                raise ValueError("Replay forbids live frames")
            for key, kind in get_type_hints(Settings).items():
                if key in values and kind is D:
                    values[key] = D(values[key])
            archived = Settings(**values, project_root=output, client_id="", client_secret="",
                                account_seq=None, live_confirmation="")
            lab = PaperLab(archived, None, output=output, policy=frame["policy"], replay=True)
        lab.apply(frame)
    if lab is None:
        raise ValueError("No frames to replay")
    return lab.report()
