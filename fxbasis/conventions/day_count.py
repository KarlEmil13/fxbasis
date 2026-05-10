"""Day count conventions and year fraction calculation."""

from enum import Enum
from datetime import date


class DayCount(Enum):
    ACT_360 = "ACT/360"
    ACT_365 = "ACT/365"
    ACT_ACT = "ACT/ACT"


def year_fraction(start: date, end: date, day_count: DayCount) -> float:
    """
    Compute the year fraction between two dates under the given day count convention.

    Parameters
    ----------
    start : date
    end : date
    day_count : DayCount

    Returns
    -------
    float
        Year fraction (e.g. 0.25 for approximately 3 months ACT/360).
    """
    days = (end - start).days
    if days < 0:
        raise ValueError(f"end date {end} is before start date {start}")

    if day_count == DayCount.ACT_360:
        return days / 360.0
    elif day_count == DayCount.ACT_365:
        return days / 365.0
    elif day_count == DayCount.ACT_ACT:
        # ISDA ACT/ACT: split across year boundaries
        if start.year == end.year:
            return days / (366.0 if _is_leap(start.year) else 365.0)
        # Simplified: weight by days in each year
        year_end = date(start.year + 1, 1, 1)
        days_this_year = (year_end - start).days
        basis_this = 366.0 if _is_leap(start.year) else 365.0
        remaining = year_fraction(year_end, end, DayCount.ACT_ACT)
        return days_this_year / basis_this + remaining

    raise ValueError(f"Unsupported day count convention: {day_count}")


def _is_leap(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
