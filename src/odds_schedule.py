"""Scheduled odds snapshots: provider update time differs from fetch time."""
from datetime import datetime, timezone, timedelta
from .bet_audit import timestamp

DAILY_REFRESH_HOUR_UTC = 15


def stamp_event(event, fetched_at, stage):
    if stage not in ("initial", "daily", "final"):
        raise ValueError("Unknown odds snapshot stage")
    return {**event, "odds_fetched_at": fetched_at.isoformat(), "odds_stage": stage}


def snapshot_context(event, now=None):
    now = now or datetime.now(timezone.utc)
    # Compatibility for callers supplying a fresh response directly.
    fetched = timestamp(event["odds_fetched_at"]) if event.get("odds_fetched_at") else now
    kickoff = timestamp(event["commence_time"])
    stage = event.get("odds_stage", "untracked")
    scheduled = fetched.replace(hour=DAILY_REFRESH_HOUR_UTC, minute=0, second=0, microsecond=0)
    if scheduled <= fetched:
        scheduled += timedelta(days=1)
    valid_until = kickoff if stage == "final" else min(kickoff, scheduled)
    return {"odds_fetched_at": fetched.isoformat(), "odds_stage": stage,
            "snapshot_valid_until": valid_until.isoformat(),
            "snapshot_valid": fetched <= now < valid_until,
            "calculated_at": now.isoformat(), "quote_basis": "scheduled_snapshot_not_live"}
