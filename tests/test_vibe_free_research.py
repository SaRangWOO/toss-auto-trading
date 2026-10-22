import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('free_research', Path(__file__).resolve().parents[1]/'research/vibe_trading/free_research.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FreeResearchTests(unittest.TestCase):
    def event(self, **changes):
        result = {'id':'one', 'at':'2026-10-22T10:00:00+09:00', 'symbol':'005930',
                  'strategy':'pullback', 'reasons':['volume'], 'returns':{'30':'0.01'}}
        result.update(changes)
        return result

    def test_finite(self):
        for value in (None, 'NaN', 'Infinity', 'bad'):
            self.assertIsNone(m.finite(value))
        self.assertEqual(m.finite('-0.01'), -.01)

    def test_selection_unique_mature_and_policy_period(self):
        event = self.event()
        ledger = {'outcomes':[self.event(returns={}), event, event,
            self.event(id='old', at='2026-10-14T10:00:00+09:00'),
            self.event(id='future', at='2026-10-23T10:00:00+09:00')]}
        self.assertEqual(m.select_events(ledger, '2026-10-22', '2026-10-15'), [event])

    def test_join_never_borrows_future_features(self):
        event = self.event()
        item = {'event_id':'one', 'metrics':{'relative_volume':2},
                'market_context':{'relative_returns':{'KOSPI':'.01','KOSDAQ':'.02'}}}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'decisions.jsonl'
            frames = [{'at':'2026-10-22T10:01:00+09:00', 'decisions':[item]}]
            path.write_text(json.dumps(frames[0]), encoding='utf-8')
            self.assertEqual(m.join_features([event], path), ([], 1))
            frames.append({'at':event['at'], 'decisions':[item,item]})
            path.write_text('\n'.join(map(json.dumps, frames)), encoding='utf-8')
            before = path.read_bytes()
            rows, missing = m.join_features([event], path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(missing, 0)
            self.assertEqual(rows[0]['relative_strength'], .01)
            self.assertEqual(path.read_bytes(), before)

    def test_cohort_outlier_removal_and_day_guard(self):
        rows = [dict(self.event(), return_30m=v) for v in [-.01]*20+[.5]]
        result = m.cohorts(rows)['pullback/only:volume']
        self.assertGreater(result['mean_net_return_30m'], 0)
        self.assertAlmostEqual(result['mean_without_best_one'], -.01)
        self.assertEqual(result['status'], 'insufficient_sample')
