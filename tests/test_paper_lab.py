from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
import gzip
import json
import tempfile
import unittest
from unittest.mock import patch

from test_strategy import settings
from toss_trader.lab_data import KST, completed_bars, opening_range, merge_completed, quote
from toss_trader.lab_strategy import evaluate, STRATEGIES
from toss_trader.paper_lab import PaperLab, default_policy, quantity, replay_frames, code_hash
from toss_trader.experiment import safe_settings


def bars():
    start = datetime(2026, 10, 8, 9, 1, tzinfo=KST)
    result = []
    for minute in range(40):
        result.append({"timestamp": (start+timedelta(minutes=minute)).isoformat(),
            "openPrice": "100", "highPrice": "100.3", "lowPrice": "99.7",
            "closePrice": "100", "volume": "1000000"})
    result[-1].update(closePrice="100.4", highPrice="100.6", volume="2000000")
    return result


def book(now, bid="100.39", ask="100.41"):
    return {"timestamp": now.isoformat(), "bids": [{"price": bid, "volume": "100000"}],
            "asks": [{"price": ask, "volume": "100000"}]}


def frame(lab, now=None, rows=None):
    now = now or datetime(2026, 10, 8, 9, 40, 5, tzinfo=KST)
    return {"schema": 3, "source_hash": code_hash(), "candle_contract": "toss_end_1m",
            "at": now.isoformat(), "policy": lab.policy, "settings": safe_settings(lab.settings), "business_day": True,
            "universe": ["A"], "instruments": {"A": {"symbol": "A", "name": "ordinary"}},
            "bars": {"A": rows or bars()}, "bar_observed_at": {"A": now.isoformat()},
            "books": {"A": book(now)}, "warnings": {"A": []}, "errors": []}


class LabDataTests(unittest.TestCase):
    def test_toss_end_time_opening_exact_30_bars(self):
        now = datetime(2026, 10, 8, 9, 30, tzinfo=KST)
        result = completed_bars(bars(), now)
        self.assertEqual(len(result), 30)
        self.assertIsNotNone(opening_range(result))
        self.assertIsNone(opening_range(result[1:]))

    def test_start_time_index_is_not_shifted_like_stock(self):
        now = datetime(2026, 10, 8, 9, 30, tzinfo=KST)
        self.assertEqual(len(completed_bars(bars(), now, convention="start")), 29)

    def test_future_previous_day_and_duplicate_handling(self):
        now = datetime(2026, 10, 8, 9, 40, tzinfo=KST)
        rows = bars()
        duplicate = deepcopy(rows[0])
        self.assertEqual(len(completed_bars(rows+[duplicate], now)), 40)
        duplicate["volume"] = "2"
        with self.assertRaises(ValueError):
            completed_bars(rows+[duplicate], now)
        rows[-1]["timestamp"] = "2026-10-08T09:41:00+09:00"
        self.assertEqual(len(completed_bars(rows, now)), 39)

    def test_timezone_and_naive_rejection(self):
        now = datetime(2026, 10, 8, 9, 40, tzinfo=KST)
        rows = bars()
        rows[0]["timestamp"] = "2026-10-08T00:01:00+00:00"
        self.assertIsNotNone(opening_range(completed_bars(rows, now)))
        rows[0]["timestamp"] = "2026-10-08T09:01:00"
        with self.assertRaises(ValueError):
            completed_bars(rows, now)

    def test_invalid_ohlcv_and_internal_gap(self):
        now = datetime(2026, 10, 8, 9, 40, tzinfo=KST)
        rows = bars()
        del rows[14]
        self.assertIsNone(opening_range(completed_bars(rows, now)))
        rows[0]["volume"] = "NaN"
        with self.assertRaises(ValueError):
            completed_bars(rows, now)

    def test_cache_keeps_opening_after_sliding_window(self):
        now = datetime(2026, 10, 8, 9, 40, tzinfo=KST)
        merged = merge_completed(bars(), bars()[-10:], now)
        self.assertIsNotNone(opening_range(merged))

    def test_stale_future_and_crossed_book(self):
        now = datetime(2026, 10, 8, 9, 40, tzinfo=KST)
        for invalid in (book(now-timedelta(seconds=91)), book(now+timedelta(seconds=1)), book(now, "101", "100")):
            with self.assertRaises(ValueError):
                quote(invalid, now)


class LabStrategyTests(unittest.TestCase):
    def test_cost_space_threshold_and_baseline_diagnostic(self):
        now = datetime(2026, 10, 8, 9, 40, 5, tzinfo=KST)
        policy = default_policy()
        self.assertEqual(policy["cost_space_multiple"], "2")
        result = evaluate("A", bars(), book(now), now, policy, "range_breakout")
        ratio = D(result["metrics"]["price_space_to_cost"])
        self.assertEqual(result["metrics"]["baseline_cost_space_pass"], ratio >= 3)
        policy["cost_space_multiple"] = str(ratio+D("0.01"))
        blocked = evaluate("A", bars(), book(now), now, policy, "range_breakout")
        self.assertFalse(blocked["gates"]["cost_space"])
        policy["cost_space_multiple"] = str(ratio-D("0.01"))
        allowed = evaluate("A", bars(), book(now), now, policy, "range_breakout")
        self.assertTrue(allowed["gates"]["cost_space"])
        self.assertEqual(blocked["metrics"], allowed["metrics"])
        self.assertEqual({k: v for k, v in blocked["gates"].items() if k != "cost_space"},
                         {k: v for k, v in allowed["gates"].items() if k != "cost_space"})
        # Synthetic costs place this fixture strictly between the two thresholds.
        ask, bid, atr = D(result["ask"]), D(result["bid"]), D(result["atr"])
        policy["commission_rate"] = str(((2*atr/D("2.5")-(ask-bid))/ask
            -2*D(policy["slippage_bps"])/10000-D(policy["sell_tax_rate"]))/2)
        policy["cost_space_multiple"] = "2"
        experimental = evaluate("A", bars(), book(now), now, policy, "range_breakout")
        self.assertEqual(experimental["status"], "eligible")
        self.assertFalse(experimental["metrics"]["baseline_cost_space_pass"])
        policy["cost_space_multiple"] = "3"
        baseline = evaluate("A", bars(), book(now), now, policy, "range_breakout")
        self.assertEqual(baseline["reasons"], ["cost_space"])

    def test_control_and_range_breakout_are_reachable_without_proxy(self):
        now = datetime(2026, 10, 8, 9, 40, 5, tzinfo=KST)
        for strategy in ("opening_control", "range_breakout"):
            result = evaluate("A", bars(), book(now), now, default_policy(), strategy)
            self.assertEqual(result["status"], "eligible", result)

    def test_pullback_is_independent_of_opening_breakout(self):
        rows = bars()
        for i, row in enumerate(rows):
            value = D("96")+D(i)/10
            row.update(openPrice=str(value), closePrice=str(value), highPrice=str(value+D("0.3")), lowPrice=str(value-D("0.3")))
        rows[36].update(openPrice="99.6", closePrice="99.4", highPrice="99.7", lowPrice="99.2")
        rows[37].update(openPrice="99.4", closePrice="99.3", highPrice="99.6", lowPrice="99.1")
        rows[38].update(openPrice="99.3", closePrice="99.4", highPrice="99.6", lowPrice="99.2")
        rows[39].update(openPrice="99.4", closePrice="100.4", highPrice="100.6", lowPrice="99.3")
        now = datetime(2026, 10, 8, 9, 40, 5, tzinfo=KST)
        result = evaluate("A", rows, book(now), now, default_policy(), "pullback")
        self.assertEqual(result["status"], "eligible", result)

    def test_unavailable_is_not_strategy_rejection(self):
        now = datetime(2026, 10, 8, 9, 40, 5, tzinfo=KST)
        self.assertEqual(evaluate("A", [], book(now), now, default_policy(), "pullback")["status"], "unavailable")
        rows = bars()
        rows[-1]["volume"] = "1"
        result = evaluate("A", rows, book(now), now, default_policy(), "range_breakout")
        self.assertEqual(result["status"], "rejected")
        self.assertIn("volume", result["reasons"])

    def test_sizing_includes_costs_and_whole_share_limits(self):
        policy = default_policy()
        self.assertEqual(quantity(D(50), D(50), D(100), D(99), D("100000000"), D(100), D(50), policy), 0)
        q = quantity(D(50000), D(50000), D(100), D(99), D("100000000"), D(100), D(45000), policy)
        self.assertLessEqual(q, 10)  # 10% of visible best ask size.
        self.assertGreater(q, 0)


class LabRunnerTests(unittest.TestCase):
    def test_data_halt_recovers_only_after_five_healthy_flat_cycles(self):
        self.lab.state.update(entry_halt=True, entry_halt_reason="held_market_data")
        start = datetime(2026, 10, 8, 9, 40, 5, tzinfo=KST)
        for i in range(5):
            self.lab.apply(frame(self.lab, start+timedelta(seconds=i*15)))
            self.assertEqual(self.lab.state["entry_halt"], i < 4)
            self.assertTrue(all(a["position"] is None for a in self.lab.state["accounts"].values()))
        self.assertIn("recovered_flat", self.lab.state["health_events"][-1]["reasons"][0])

    def test_infrastructure_or_unknown_halts_do_not_auto_recover(self):
        for reason in ("infrastructure", "unknown", "manual", None):
            lab = PaperLab(self.config, object(), output=self.root/str(reason))
            lab.state.update(entry_halt=True, entry_halt_reason=reason)
            for i in range(5):
                lab.apply(frame(lab, datetime(2026, 10, 8, 9, 40, 5, tzinfo=KST)+timedelta(seconds=i*15)))
            self.assertTrue(lab.state["entry_halt"])

    def test_bad_coverage_breaks_recovery_streak(self):
        self.lab.state.update(entry_halt=True, entry_halt_reason="held_market_data")
        f = frame(self.lab)
        self.lab.apply(f)
        self.assertEqual(self.lab.state["recovery_cycles"], 1)
        f2 = frame(self.lab, datetime.fromisoformat(f["at"])+timedelta(seconds=15))
        f2["books"]["A"] = book(datetime.fromisoformat(f2["at"]), "101", "100")
        self.lab.apply(f2)
        self.assertEqual(self.lab.state["recovery_cycles"], 0)
        self.assertTrue(self.lab.state["entry_halt"])

    def test_scheduler_and_watchdog_start_at_market_open(self):
        root = Path(__file__).resolve().parents[1]
        installer = (root/"scripts/install-task.ps1").read_text(encoding="utf-8")
        watchdog = (root/"scripts/watchdog.ps1").read_text(encoding="utf-8")
        self.assertIn('-At "09:00"', installer)
        self.assertIn('[TimeSpan]::Parse("09:00")', watchdog)
        self.assertNotIn('"09:04"', installer+watchdog)

    def test_timeout_is_conditional_not_unconditional_30_minute_exit(self):
        start = datetime(2026, 10, 8, 10, 0, tzinfo=KST)
        for seconds, bid, expected in ((1799, "100.1", None),
                                       (1800, "100.1", "no_progress_timeout"),
                                       (1800, "100.6", None),
                                       (1, "98.9", "structural_stop")):
            with self.subTest(seconds=seconds, bid=bid):
                a = deepcopy(self.lab.state["accounts"]["pullback/research"])
                a["cash"] = "999900"
                a["position"] = {"symbol": "A", "quantity": 1, "entry": "100", "entry_ask": "100",
                    "entry_cost": "100", "stop": "99", "risk": "1", "atr": "1",
                    "high": "100", "opened_at": start.isoformat()}
                now = start+timedelta(seconds=seconds)
                self.lab._exit_and_mark(a, {"A": book(now, bid, str(D(bid)+D("0.1")))}, now, "research")
                self.assertEqual(a["trades"][-1]["reason"] if a["trades"] else None, expected)

    def test_profile_daily_limits_are_separate(self):
        lab = PaperLab(replace(self.config, max_daily_loss_krw=D("1000")), object(), output=self.root/"limits")
        self.assertEqual(lab.daily_loss_limit(lab.state["accounts"]["pullback/research"], "research"), D("10000"))
        self.assertEqual(lab.daily_loss_limit(lab.state["accounts"]["pullback/execution"], "execution"), D("500"))

    def test_remaining_daily_budget_bounds_quantity_including_costs(self):
        p = default_policy()
        for remaining in (D("0"), D("20"), D("100")):
            q = quantity(D("1000000"), D("1000000"), D("100"), D("99"),
                         D("100000000"), D("100000"), D("1000000"), p,
                         remaining_loss=remaining, bid=D("98"))
            unit_loss = D("100")*(1+D(p["slippage_bps"])/10000)*(1+D(p["commission_rate"])) - D("98")*(1-D(p["slippage_bps"])/10000)*(1-D(p["commission_rate"])-D(p["sell_tax_rate"]))
            self.assertLessEqual(q*unit_loss, remaining)
        self.assertEqual(quantity(D(1000), D(1000), D(100), D(99), D("100000000"),
                                 D(1000), D(1000), p, remaining_loss=D("-1")), 0)

    def test_research_position_not_closed_by_execution_absolute_limit(self):
        lab = PaperLab(replace(self.config, max_daily_loss_krw=D("1000")), object(), output=self.root/"exits")
        now = datetime(2026, 10, 8, 10, 0, tzinfo=KST)
        a = lab.state["accounts"]["pullback/research"]
        a.update(cash="600000", day="2026-10-08", last_equity="1000000")
        a["position"] = {"symbol": "A", "quantity": 4000, "entry": "100", "entry_ask": "100",
                         "entry_cost": "400000", "stop": "98", "risk": "2", "atr": "1",
                         "high": "100", "opened_at": now.isoformat()}
        lab._exit_and_mark(a, {"A": book(now, "99.9", "100")}, now, "research")
        self.assertIsNotNone(a["position"])
        lab._exit_and_mark(a, {"A": book(now, "99.9", "100")}, now, "execution")
        self.assertIsNone(a["position"])
        self.assertEqual(a["trades"][-1]["reason"], "daily_loss_guard")

    def test_flat_migration_preserves_losses_halts_and_progress(self):
        from toss_trader.paper_lab import migrate_flat_risk_policy
        from toss_trader.experiment import write_json
        f = frame(self.lab)
        self.lab.apply(f)
        now = datetime.fromisoformat(f["at"])+timedelta(seconds=30)
        f2 = frame(self.lab, now)
        f2["books"]["A"] = book(now, "98", "98.1")
        self.lab.apply(f2)
        self.lab.state["entry_halt"] = True
        original = deepcopy(self.lab.state)
        write_json(self.lab.path, original)
        old_manifest = deepcopy(self.lab.manifest)
        del old_manifest["policy"]["research_daily_loss_krw"]
        write_json(self.lab.root/"manifest.json", old_manifest)
        result = migrate_flat_risk_policy(self.config, self.lab.root, self.root/"migrated")
        new_state = json.loads((self.root/"migrated"/"ledger.json").read_text(encoding="utf-8"))
        for key, value in original.items():
            self.assertEqual(new_state[key], value)
        self.assertTrue(result["entry_halt"])
        self.assertTrue(all(a["current_policy_closed_trades"] == 0 for a in result["accounts"].values()))
        self.assertTrue(any(D(a["net_pnl"]) < 0 for a in result["accounts"].values()))

    def test_migration_rejects_open_positions(self):
        from toss_trader.paper_lab import migrate_flat_risk_policy
        self.lab.apply(frame(self.lab))
        with self.assertRaisesRegex(ValueError, "flat_accounts"):
            migrate_flat_risk_policy(self.config, self.lab.root, self.root/"unsafe")

    def test_same_policy_migration_classifies_but_does_not_clear_reviewed_halt(self):
        from toss_trader.paper_lab import migrate_flat_risk_policy
        from toss_trader.experiment import write_json
        self.lab.state.update(entry_halt=True, errors=10)
        self.lab.state["accounts"]["pullback/research"]["halted"] = True
        write_json(self.lab.path, self.lab.state)
        result = migrate_flat_risk_policy(self.config, self.lab.root, self.root/"diagnostics-version",
                                         same_policy=True, reviewed_data_halt=True)
        self.assertTrue(result["entry_halt"])
        self.assertEqual(result["entry_halt_reason"], "held_market_data")
        self.assertEqual(result["errors"], 10)
        migrated = json.loads((self.root/"diagnostics-version"/"ledger.json").read_text(encoding="utf-8"))
        self.assertEqual(migrated["accounts"], self.lab.state["accounts"])

    def test_market_context_does_not_change_baseline_orders(self):
        f = frame(self.lab)
        self.lab.apply(f)
        other = PaperLab(self.config, object(), output=self.root/"context-only")
        with patch("toss_trader.paper_lab.market_context", return_value={
            "status": "available", "regime": "falling", "shadow_relative_strength": False,
            "shadow_defensive": False}):
            other.apply(frame(other))
        for name, account in self.lab.state["accounts"].items():
            self.assertEqual(account["cash"], other.state["accounts"][name]["cash"])
            self.assertEqual(account["entries"], other.state["accounts"][name]["entries"])

    def test_continuous_entry_window_boundaries(self):
        for clock, expected in (("09:30", 0), ("09:31", 3), ("11:30", 3),
                                ("12:30", 3), ("13:30", 3), ("14:49", 3),
                                ("14:50", 0), ("15:15", 0)):
            with self.subTest(clock=clock):
                lab = PaperLab(self.config, object(), output=self.root / clock.replace(":", ""))
                now = datetime.fromisoformat("2026-10-08T"+clock+":05+09:00")
                # Mock only the strategy result: test scheduling independently
                # from candle availability, without any orders or network.
                with patch("toss_trader.paper_lab.evaluate", return_value={
                    "status": "unavailable", "strategy": "range_breakout",
                    "reasons": ["test_data_unavailable"]}) as evaluate_mock:
                    lab.apply(frame(lab, now))
                    self.assertEqual(evaluate_mock.call_count, expected)
                self.assertTrue(all(a["position"] is None for a in lab.state["accounts"].values()))

    def test_daily_report_uses_only_existing_atomic_comparison(self):
        from toss_trader.paper_lab import write_lab_report
        self.lab.apply(frame(self.lab))
        original = self.lab.path.read_bytes()
        result = write_lab_report(self.root)
        self.assertEqual(json.loads(result.read_text(encoding="utf-8")), self.lab.report())
        self.assertEqual(original, self.lab.path.read_bytes())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = settings(self.root)
        self.lab = PaperLab(self.config, object())

    def test_live_refused(self):
        with self.assertRaises(ValueError):
            PaperLab(replace(self.config, mode="live"), object())

    def test_policy_and_code_manifest_prevent_mixing(self):
        p = default_policy()
        p["min_relative_volume"] = "1.3"
        with self.assertRaises(ValueError):
            PaperLab(self.config, object(), policy=p)

    def test_six_accounts_entries_and_restart_dedup(self):
        f = frame(self.lab)
        self.lab.apply(f)
        self.assertEqual(len(self.lab.state["accounts"]), 6)
        self.assertIsNotNone(self.lab.state["accounts"]["range_breakout/execution"]["position"])
        restarted = PaperLab(self.config, object())
        self.assertEqual(restarted.state, self.lab.state)
        with self.assertRaises(ValueError):
            restarted.apply(f)

    def test_costs_exit_and_no_same_cycle_reentry(self):
        f = frame(self.lab)
        self.lab.apply(f)
        now = datetime.fromisoformat(f["at"])+timedelta(seconds=30)
        f2 = frame(self.lab, now)
        f2["books"]["A"] = book(now, "98", "98.1")
        self.lab.apply(f2)
        a = self.lab.state["accounts"]["range_breakout/execution"]
        self.assertIsNone(a["position"])
        self.assertEqual(len(a["trades"]), 1)
        self.assertLess(D(a["trades"][0]["net"]), 0)
        self.assertLess(D(a["trades"][0]["stress_net"]), D(a["trades"][0]["net"]))

    def test_missing_exit_quote_does_not_invent_liquidation(self):
        f = frame(self.lab)
        self.lab.apply(f)
        f2 = frame(self.lab, datetime.fromisoformat(f["at"])+timedelta(seconds=30))
        f2["books"] = {}
        self.lab.apply(f2)
        self.assertIsNotNone(self.lab.state["accounts"]["range_breakout/execution"]["position"])
        self.assertEqual(self.lab.state["errors"], 1)

    def test_holiday_and_bad_data_never_enter(self):
        f = frame(self.lab)
        f["business_day"] = False
        self.lab.apply(f)
        self.assertTrue(all(a["position"] is None for a in self.lab.state["accounts"].values()))

    def test_data_availability_recorded_separately(self):
        f = frame(self.lab)
        f["bars"]["A"] = []
        self.lab.apply(f)
        coverage = self.lab.state["coverage"]["2026-10-08"]
        self.assertEqual(coverage["available"], 0)
        self.assertEqual(coverage["data_errors"], 3)
        self.assertFalse(coverage["gate_failures"])

    def test_collection_cutoff_prevents_using_forming_bar(self):
        f = frame(self.lab)
        f["bar_observed_at"]["A"] = "2026-10-08T09:39:59+09:00"
        self.lab.apply(f)
        self.assertEqual(self.lab.state["bars"]["A"][-1]["timestamp"], "2026-10-08T09:39:00+09:00")

    def test_sequential_replay_matches_state_and_rejects_existing_output(self):
        paths = []
        f = frame(self.lab)
        for index in range(2):
            now = datetime.fromisoformat(f["at"])+timedelta(seconds=index*30)
            current = frame(self.lab, now)
            self.lab.apply(current)
            path = self.root / f"{index}.json.gz"
            with gzip.open(path, "wt", encoding="utf-8") as stream:
                json.dump(current, stream, default=str)
            paths.append(path)
        result = replay_frames(self.config, paths, self.root/"replayed")
        self.assertEqual(result["accounts"], self.lab.report()["accounts"])
        with self.assertRaises(ValueError):
            replay_frames(self.config, paths, self.root/"replayed")

    def test_read_only_collection_cannot_access_order_endpoint(self):
        class Client:
            def kr_market_calendar(self):
                return {"today": {"date": str(datetime.now(KST).date()), "integrated": None}}
            def create_order(self, *args):
                raise AssertionError("Order API must never be called")
        self.lab.source = Client()
        collected = self.lab.collect()
        self.assertFalse(collected["business_day"])
        self.assertEqual(collected["errors"], [])

    def test_completed_trial_still_manages_position(self):
        f = frame(self.lab)
        self.lab.apply(f)
        self.lab.state["progress"]["days"] = {str(i): {"completed": True} for i in range(5)}
        now = datetime.fromisoformat(f["at"])+timedelta(seconds=30)
        next_frame = frame(self.lab, now)
        next_frame["books"]["A"] = book(now, "98", "98.1")
        self.lab.apply(next_frame)
        self.assertTrue(all(a["position"] is None for a in self.lab.state["accounts"].values()))

    def test_checkpoint_late_sample_is_missing_not_future_filled(self):
        f = frame(self.lab)
        self.lab.apply(f)
        now = datetime.fromisoformat(f["at"])+timedelta(minutes=7)
        self.lab.apply(frame(self.lab, now))
        self.assertIsNone(self.lab.state["outcomes"][0]["returns"]["5"])

    def test_missing_one_candidate_does_not_block_other_valid_candidates(self):
        f = frame(self.lab)
        f["universe"].append("B")
        f["instruments"]["B"] = {"symbol": "B", "name": "ordinary"}
        f["warnings"]["B"] = []
        self.lab.apply(f)
        self.assertIsNotNone(self.lab.state["accounts"]["range_breakout/execution"]["position"])
        self.assertEqual(self.lab.state["coverage"]["2026-10-08"]["data_errors"], 3)

    def test_insufficient_bid_size_blocks_fake_full_exit(self):
        f = frame(self.lab)
        self.lab.apply(f)
        now = datetime.fromisoformat(f["at"])+timedelta(seconds=30)
        next_frame = frame(self.lab, now)
        next_frame["books"]["A"] = book(now, "98", "98.1")
        next_frame["books"]["A"]["bids"][0]["volume"] = "1"
        self.lab.apply(next_frame)
        a = self.lab.state["accounts"]["range_breakout/execution"]
        self.assertTrue(a["halted"])
        self.assertIsNotNone(a["position"])
        self.assertEqual(len(a["trades"]), 0)

    def test_drawdown_includes_entry_cost_immediately(self):
        self.lab.apply(frame(self.lab))
        a = self.lab.state["accounts"]["range_breakout/execution"]
        self.assertGreater(D(a["drawdown"]), 0)
        self.assertLess(D(a["last_equity"]), D(a["initial"]))

    def test_infrastructure_error_circuit_persists_across_restart(self):
        now = datetime(2026, 10, 8, 9, 40, 5, tzinfo=KST)
        for i in range(self.config.max_consecutive_errors):
            f = frame(self.lab, now+timedelta(seconds=30*i))
            f["errors"] = ["collection_failed"]
            self.lab.apply(f)
        restarted = PaperLab(self.config, object())
        self.assertTrue(restarted.state["entry_halt"])
        self.assertTrue(all(a["position"] is None for a in restarted.state["accounts"].values()))

    def test_episode_not_recounted_on_same_completed_bar(self):
        f = frame(self.lab)
        self.lab.apply(f)
        count = len(self.lab.state["outcomes"])
        self.lab.apply(frame(self.lab, datetime.fromisoformat(f["at"])+timedelta(seconds=20)))
        self.assertEqual(len(self.lab.state["outcomes"]), count)

    def test_warnings_and_missing_metadata_block_entries(self):
        f = frame(self.lab)
        f["warnings"]["A"] = ["halted"]
        self.lab.apply(f)
        self.assertTrue(all(a["position"] is None for a in self.lab.state["accounts"].values()))

    def test_force_exit_without_new_entry(self):
        f = frame(self.lab)
        self.lab.apply(f)
        now = datetime(2026, 10, 8, 15, 15, tzinfo=KST)
        self.lab.apply(frame(self.lab, now))
        a = self.lab.state["accounts"]["range_breakout/execution"]
        self.assertIsNone(a["position"])
        self.assertEqual(a["trades"][0]["reason"], "session_exit")

    def test_replay_uses_recorded_risk_settings_not_local_settings(self):
        f = frame(self.lab)
        self.lab.apply(f)
        path = self.root/"frame.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(f, stream, default=str)
        different = replace(self.config, max_position_rate=D("0.001"))
        result = replay_frames(different, [path], self.root/"replay-other-config")
        self.assertEqual(result["accounts"], self.lab.report()["accounts"])

    def test_source_version_mismatch_refused(self):
        f = frame(self.lab)
        f["source_hash"] = "different"
        path = self.root/"bad.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(f, stream, default=str)
        with self.assertRaises(ValueError):
            replay_frames(self.config, [path], self.root/"bad-replay")
