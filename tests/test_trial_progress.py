import unittest
from datetime import datetime, timedelta
from toss_trader.engine import KST
from toss_trader.trial_progress import new_progress, observe, summary


class TrialProgressTests(unittest.TestCase):
    def day(self, progress, day, business=True, start=(9, 4), gap=False,
            healthy=True, flat=True):
        now = datetime(2026, 10, day, *start, tzinfo=KST)
        end = now.replace(hour=15, minute=40)
        while now <= end:
            observe(progress, now, business, healthy, flat)
            now += timedelta(minutes=3 if gap and now.hour == 10 and now.minute == 0 else 1)

    def test_five_days_persist_and_do_not_double_count(self):
        import json
        progress = new_progress()
        for day in (7, 8, 12, 13, 14):
            self.day(progress, day)
            progress = json.loads(json.dumps(progress))
        self.day(progress, 14)
        self.day(progress, 15)
        self.assertEqual(summary(progress)["completed_days"], 5)
        self.assertEqual(summary(progress)["status"], "complete")
        self.assertNotIn("2026-10-15", progress["days"])

    def test_holiday_unknown_late_gap_errors_and_holdings_do_not_count(self):
        cases = ({"business": False}, {"business": None}, {"start": (10, 0)},
                 {"gap": True}, {"healthy": False}, {"flat": False})
        for case in cases:
            with self.subTest(case=case):
                progress = new_progress()
                self.day(progress, 7, **case)
                self.assertEqual(summary(progress)["completed_days"], 0)

    def test_warmup_not_counted_and_incomplete_day_not_credited(self):
        progress = new_progress()
        observe(progress, datetime(2026, 10, 7, 8, 30, tzinfo=KST), None, False, True)
        self.assertFalse(progress["days"])
        observe(progress, datetime(2026, 10, 7, 9, 4, tzinfo=KST), True, True, True)
        self.assertEqual(summary(progress)["completed_days"], 0)
