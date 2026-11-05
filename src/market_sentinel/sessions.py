"""Portable regular-session calendar validation, shared with daily reports."""

import calendar
from datetime import date, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


class ScheduleError(ValueError):
    """Safe operational diagnostic; never contains provider responses or secrets."""


def normalize_calendar(payload, year, month):
    """Require every calendar day, explicit open/closed and valid regular hours."""
    try:
        body = payload["calendar"]
        rows = body["days"]["day"]
        if body["year"] != year or body["month"] != month or not isinstance(rows, list):
            raise ValueError
        result = {}
        for row in rows:
            day = date.fromisoformat(row["date"])
            if str(day) != row["date"] or (day.year, day.month) != (year, month) or str(day) in result:
                raise ValueError
            if row["status"] == "closed":
                result[str(day)] = None
            elif row["status"] == "open":
                start, end = row["open"]["start"], row["open"]["end"]
                opening, closing = time.fromisoformat(start), time.fromisoformat(end)
                if (day.weekday() >= 5 or opening.tzinfo or closing.tzinfo or
                        opening >= closing or start != opening.strftime("%H:%M") or end != closing.strftime("%H:%M")):
                    raise ValueError
                result[str(day)] = {"start": start, "end": end}
            else:
                raise ValueError
        expected = {str(date(year, month, d)) for d in range(1, calendar.monthrange(year, month)[1] + 1)}
        if set(result) != expected:
            raise ValueError
        return result
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ScheduleError("Incomplete or invalid Tradier market calendar; no session assumed.") from None


