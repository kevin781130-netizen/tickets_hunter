# -*- coding: utf-8 -*-
"""Pure scheduling primitives shared by booking adapters.

No browser, network, site selectors, or submission logic. Site-specific policy
(seven-day horizon, retryable outcomes, etc.) stays with the adapter.
"""
from datetime import date, datetime, time, timedelta


def release_datetime(target_day, *, days_before, tz):
    """Return the adapter-configured opening midnight in its local timezone."""
    if not isinstance(target_day, date) or isinstance(target_day, datetime):
        raise ValueError("invalid target day")
    if isinstance(days_before, bool) or not isinstance(days_before, int) or days_before < 0:
        raise ValueError("invalid release horizon")
    if tz is None or tz.utcoffset(None) is None:
        raise ValueError("release timezone required")
    return datetime.combine(target_day - timedelta(days=days_before),
                            time.min, tzinfo=tz)


def seconds_until(target, now=None):
    """Signed seconds until an aware opening time, independent of host timezone."""
    if not isinstance(target, datetime) or target.tzinfo is None:
        raise ValueError("target must have timezone")
    current = now or datetime.now(target.tzinfo)
    if current.tzinfo is None:
        raise ValueError("now must have timezone")
    return (target - current.astimezone(target.tzinfo)).total_seconds()


def has_retry_budget(*, now, deadline, interval):
    """True if a future retry delay fits completely inside a monotonic window."""
    return now + interval <= deadline
