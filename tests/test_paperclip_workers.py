import importlib.util
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location('paperclip_worker', Path(__file__).resolve().parents[1]/'research/paperclip/worker.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class PaperclipWorkerTests(unittest.TestCase):
    def test_research_refreshes_without_overwriting_old_analysis(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(w, 'OUTPUT', Path(temp)):
            now = datetime.fromisoformat('2026-10-22T16:00:00+09:00')
            folder = Path(temp)/'2026-10-22'
            w.write(folder/'research.json', {'old': True})
            with patch.object(w, 'ready_for_close'), patch.object(w, 'research', return_value={'day':'2026-10-22'}), patch.object(w, 'free_research', return_value={'llm_calls':False}) as free:
                result = w.run('research', now)
                self.assertFalse(result['free_research']['llm_calls'])
                self.assertEqual(w.run('research', now), result)
                free.assert_called_once()
            self.assertEqual(w.read(folder/'research.json'), {'old':True})

    def test_two_slots_and_crash_safe_release(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(w, 'OUTPUT', Path(temp)):
            with w.capacity() as first, w.capacity() as second, w.capacity() as third:
                self.assertTrue(first)
                self.assertTrue(second)
                self.assertFalse(third)
            with w.capacity() as released:
                self.assertTrue(released)

    def test_unchanged_operations_does_not_create_or_update_duplicate_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            w.write(root/'state/paperclip.json', {'company_id': 'company', 'agents': {'operations': 'agent'}})
            calls = []
            def api(path, payload=None, method=None):
                calls.append((path, payload))
                return [] if payload is None else {'id': 'issue'}
            now = datetime.fromisoformat('2026-10-22T10:00:00+09:00')
            with patch.object(w, 'ROOT', root), patch.object(w, 'OUTPUT', root/'output'), patch.dict('sys.modules', {'bootstrap': SimpleNamespace(api=api)}):
                w.publish('operations', {'alerts': [], 'at': 'first'}, now)
                w.publish('operations', {'alerts': [], 'at': 'second'}, now)
            self.assertEqual(len(calls), 2) # one lookup, one creation, no repeated write

    def fixture(self, root, last='2026-10-22T15:39:45+09:00', position=None):
        w.write(root/'ledger.json', {'last_at': last, 'accounts': {'research': {'position': position}}, 'entry_halt': False})
        w.write(root/'heartbeat.json', {'updated_at': last})
        w.write(root/'daily/2026-10-22.json', {})

    def test_unfinished_day_and_open_positions_never_mark_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root, last='2026-10-22T09:35:00+09:00')
            with self.assertRaises(ValueError):
                w.ready_for_close('2026-10-22', root)
            self.fixture(root, position={'symbol': '005930'})
            with self.assertRaises(ValueError):
                w.ready_for_close('2026-10-22', root)
            self.fixture(root)
            self.assertIsNotNone(w.ready_for_close('2026-10-22', root))

    def test_stale_is_alert_only_during_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root, last='2026-10-21T09:35:00+09:00')
            before = (root/'ledger.json').read_bytes()
            for clock, expected in [('08:50', False), ('09:05', True), ('16:00', False)]:
                r = w.operations(datetime.fromisoformat('2026-10-22T'+clock+':00+09:00'), root)
                self.assertEqual(bool(r['alerts']), expected)
            self.assertEqual(before, (root/'ledger.json').read_bytes())

    def test_research_excludes_other_days_and_distinguishes_repeated_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            item = {'symbol': '005930', 'strategy': 'pullback', 'status': 'rejected', 'reasons': ['volume']}
            frames = [{'at': day+'T10:00:00+09:00', 'decisions': [item]} for day in ['2026-10-21', '2026-10-22', '2026-10-22']]
            frames.append({'at': '2026-10-22T10:01:00+09:00', 'decisions': [{'symbol': '122630', 'status': 'safety_block', 'reasons': ['instrument_or_warning']}]})
            (root/'decisions.jsonl').write_text('\n'.join(json.dumps(f) for f in frames), encoding='utf-8')
            result = w.research('2026-10-22', root)
            self.assertEqual(result['observations'], 3)
            self.assertEqual(result['distinct_symbols_by_reason']['pullback:rejected:volume'], 1)
            self.assertEqual(result['reason_observations']['universe:safety_block:instrument_or_warning'], 1)

    def test_positive_total_with_negative_cost_stress_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            w.write(root/'performance.json', {'day': '2026-10-22', 'reconciliation_passed': True, 'summary': {
                'pullback/research': {'net_pnl_krw': '10', 'net_without_best_two_krw': '2', 'cost_stress_net_krw': '-1'}}})
            w.write(root/'research-v2.json', {'day': '2026-10-22', 'free_research': {'llm_calls': False}})
            result = w.validation('2026-10-22', root)
            self.assertEqual(result['verdicts']['pullback/research'], 'not_eligible_for_promotion')
            self.assertFalse(result['live_promotion'])
