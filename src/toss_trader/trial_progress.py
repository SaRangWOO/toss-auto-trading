"""Persistent coverage accounting; never infer completed days from trade count."""
from datetime import datetime


def new_progress():
    return {"schema": 1, "target_days": 5, "days": {}}


def completed_days(progress):
    return sum(bool(day.get("completed")) for day in progress["days"].values())


def observe(progress, now, business_day, healthy, flat):
    """Count 09:05 through 15:39 coverage, with at most 90s between cycles.

    15:39 tolerates the runner's final cycle crossing its 15:40 stop time.
    Earlier warm-up calls are not part of coverage. Missing calendar is unknown,
    not a holiday. Once earned, a completed date is immutable and idempotent.
    """
    if completed_days(progress) >= progress["target_days"]:
        return
    clock = now.strftime("%H:%M")
    if clock < "09:00":
        return
    key = now.date().isoformat()
    day = progress["days"].setdefault(key, {
        "first_at": now.isoformat(), "last_at": None, "cycles": 0,
        "business_day": None, "reasons": [], "completed": False})
    if day["completed"]:
        return
    reasons = day["reasons"]
    if day["cycles"] == 0 and clock > "09:05":
        reasons.append("late_start")
    if day["last_at"]:
        gap = (now - datetime.fromisoformat(day["last_at"])).total_seconds()
        if gap < 0 or gap > 90:
            if "coverage_gap" not in reasons:
                reasons.append("coverage_gap")
    day["last_at"] = now.isoformat()
    day["cycles"] += 1
    day["business_day"] = business_day
    if not healthy and "data_or_cycle_error" not in reasons:
        reasons.append("data_or_cycle_error")
    day["completed"] = bool(business_day is True and not reasons and
                            clock >= "15:39" and flat)


def summary(progress):
    count = completed_days(progress)
    return {"target_days": progress["target_days"], "completed_days": count,
            "remaining_days": max(0, progress["target_days"] - count),
            "status": "complete" if count >= progress["target_days"] else "collecting",
            "days": progress["days"]}
