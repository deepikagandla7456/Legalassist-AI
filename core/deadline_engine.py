from datetime import datetime, time, timedelta, date
from zoneinfo import ZoneInfo
from typing import List, Optional, Dict, Any


def _parse_date(value: Any, tz: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        # expect ISO string
        dt = datetime.fromisoformat(str(value))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz))
    else:
        # convert to requested tz
        dt = dt.astimezone(ZoneInfo(tz))

    return dt


def _is_weekend(dt: date) -> bool:
    return dt.weekday() >= 5


def calculate_deadline(
    start: Any,
    business_days: int,
    timezone: str = "UTC",
    exclude_weekends: bool = True,
    holidays: Optional[List[str]] = None,
    jurisdiction: Optional[str] = None,
    emergency_extension_days: int = 0,
    filing_time: Optional[str] = None,
) -> Dict[str, Any]:
    """Calculate a deadline applying business day rules, holidays, and jurisdiction rules.

    - `start`: ISO datetime string or datetime/date
    - `business_days`: number of business days to add
    - `timezone`: IANA tz name
    - `holidays`: list of ISO date strings (YYYY-MM-DD)
    - `jurisdiction`: optional key for jurisdiction-specific rules (POC)
    - `emergency_extension_days`: extra days added for emergency relief
    - `filing_time`: optional HH:MM to check against jurisdiction cutoff
    """
    tz = timezone or "UTC"
    dt = _parse_date(start, tz)

    holidays_set = set(holidays or [])

    remaining = max(0, int(business_days))
    current = dt

    # If business_days is zero, deadline is same day but still may be adjusted
    steps = 0
    while remaining > 0:
        # move to next day at same local wall clock
        current = current + timedelta(days=1)
        steps += 1
        d = current.date()

        if exclude_weekends and _is_weekend(d):
            continue

        if d.isoformat() in holidays_set:
            continue

        remaining -= 1

    adjusted_for_weekends_holidays = current

    # Apply jurisdiction-specific rules (POC)
    jurisdiction_adjustment = 0
    if jurisdiction:
        # Example rule: if filing after 17:00 local time, add 1 day in some jurisdictions
        rules = {
            "NY": {"cutoff_hour": 17, "add_days_after_cutoff": 1},
            "CA": {"cutoff_hour": 16, "add_days_after_cutoff": 1},
        }
        r = rules.get(jurisdiction.upper())
        if r and filing_time:
            try:
                fh = int(filing_time.split(":")[0])
                if fh >= r.get("cutoff_hour", 24):
                    jurisdiction_adjustment = r.get("add_days_after_cutoff", 0)
            except Exception:
                jurisdiction_adjustment = 0

    final = adjusted_for_weekends_holidays + timedelta(days=jurisdiction_adjustment + int(emergency_extension_days))

    return {
        "deadline": final.isoformat(),
        "components": {
            "start": dt.isoformat(),
            "after_business_day_add": adjusted_for_weekends_holidays.isoformat(),
            "jurisdiction_adjustment_days": jurisdiction_adjustment,
            "emergency_extension_days": int(emergency_extension_days),
            "timezone": tz,
            "steps_taken": steps,
        },
    }


__all__ = ["calculate_deadline"]
