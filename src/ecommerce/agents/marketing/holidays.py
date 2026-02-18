"""
Holiday Detection Logic for Seasonal Marketing

Provides utilities for detecting upcoming holidays and generating
seasonal campaign data. Includes a full US retail calendar with
retail context for campaign suggestions.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional
import re


@dataclass(frozen=True)
class Holiday:
    """Represents a holiday with name, date, and retail context."""
    name: str
    date: date
    retail_context: str = ""


def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
    """
    Get the nth occurrence of a weekday in a month.

    Args:
        year: Year
        month: Month (1-12)
        weekday: Day of week (Monday=0 ... Sunday=6)
        n: Which occurrence (1-5)

    Returns:
        Date of the nth weekday
    """
    d = date(year, month, 1)
    days_ahead = (weekday - d.weekday()) % 7
    first = d + timedelta(days=days_ahead)
    return first + timedelta(days=7 * (n - 1))


def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """
    Get the last occurrence of a weekday in a month.

    Args:
        year: Year
        month: Month (1-12)
        weekday: Day of week (Monday=0 ... Sunday=6)

    Returns:
        Date of the last weekday
    """
    if month < 12:
        d = date(year, month + 1, 1) - timedelta(days=1)
    else:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    days_back = (d.weekday() - weekday) % 7
    return d - timedelta(days=days_back)


def _easter_date(year: int) -> date:
    """Compute Easter Sunday using the Anonymous Gregorian algorithm."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def get_us_holidays_for_year(year: int) -> list[Holiday]:
    """
    Get all major US retail holidays for a given year.

    Includes fixed-date holidays, floating holidays, and key
    retail events with retail context for campaign suggestions.

    Args:
        year: Year to get holidays for

    Returns:
        List of Holiday objects sorted by date
    """
    # Floating holidays
    presidents_day = _nth_weekday_of_month(year, 2, weekday=0, n=3)
    easter = _easter_date(year)
    mothers_day = _nth_weekday_of_month(year, 5, weekday=6, n=2)
    memorial_day = _last_weekday_of_month(year, 5, weekday=0)
    fathers_day = _nth_weekday_of_month(year, 6, weekday=6, n=3)
    labor_day = _nth_weekday_of_month(year, 9, weekday=0, n=1)
    thanksgiving = _nth_weekday_of_month(year, 11, weekday=3, n=4)
    black_friday = thanksgiving + timedelta(days=1)
    cyber_monday = thanksgiving + timedelta(days=4)

    holidays = [
        Holiday("New Year's Day", date(year, 1, 1), "Fitness, organization, fresh start"),
        Holiday("Valentine's Day", date(year, 2, 14), "Jewelry, flowers, dining, experiences"),
        Holiday("Presidents' Day", presidents_day, "Clearance, home goods, mattress sales"),
        Holiday("St. Patrick's Day", date(year, 3, 17), "Themed apparel & accessories"),
        Holiday("Easter", easter, "Gifting, family apparel, candy"),
        Holiday("Mother's Day", mothers_day, "Jewelry, beauty, flowers"),
        Holiday("Memorial Day", memorial_day, "Summer outdoor, BBQ, travel"),
        Holiday("Juneteenth", date(year, 6, 19), "Values-led marketing, community events"),
        Holiday("Father's Day", fathers_day, "Tech, grilling, outdoor"),
        Holiday("Independence Day", date(year, 7, 4), "Outdoor, patriotic apparel, BBQ"),
        Holiday("Labor Day", labor_day, "Back-to-school, end-of-summer clearance"),
        Holiday("Halloween", date(year, 10, 31), "Costumes, candy, decor"),
        Holiday("Thanksgiving", thanksgiving, "Home, kitchen, family"),
        Holiday("Black Friday", black_friday, "Electronics, doorbuster deals"),
        Holiday("Cyber Monday", cyber_monday, "Online deals, tech, subscriptions"),
        Holiday("Christmas", date(year, 12, 25), "Peak gifting across all categories"),
    ]

    holidays.sort(key=lambda h: h.date)
    return holidays


def get_next_upcoming_holiday(today: Optional[date] = None) -> Optional[Holiday]:
    """
    Get the next upcoming holiday from today.

    Args:
        today: Reference date (defaults to today)

    Returns:
        The next Holiday or None if none found
    """
    if today is None:
        today = date.today()

    candidates = (
        get_us_holidays_for_year(today.year) +
        get_us_holidays_for_year(today.year + 1)
    )

    candidates = [h for h in candidates if h.date >= today]
    candidates.sort(key=lambda h: h.date)

    return candidates[0] if candidates else None


def get_retail_calendar(today: Optional[date] = None) -> list[dict]:
    """
    Return all holidays for the year with days_until and status.

    Each entry includes:
    - name, date (ISO string), days_until, retail_context
    - status: "past" | "active" (within 42 days) | "upcoming"

    Args:
        today: Reference date (defaults to today)

    Returns:
        List of dicts sorted chronologically
    """
    if today is None:
        today = date.today()

    holidays = get_us_holidays_for_year(today.year)

    result = []
    for h in holidays:
        days_until = (h.date - today).days
        if days_until < 0:
            status = "past"
        elif days_until <= 42:
            status = "active"
        else:
            status = "upcoming"

        result.append({
            "name": h.name,
            "date": h.date.isoformat(),
            "days_until": days_until,
            "retail_context": h.retail_context,
            "status": status,
        })

    return result


def generate_discount_code(holiday_name: str, category: str, year: int) -> str:
    """
    Generate a discount code name for a seasonal campaign.

    Args:
        holiday_name: Name of the holiday
        category: Product category
        year: Year for the code

    Returns:
        Discount code string (max 20 chars)
    """
    base = re.sub(r"[^A-Za-z0-9]", "", holiday_name).upper()
    cat = re.sub(r"[^A-Za-z0-9]", "", (category or "SALE")).upper()
    yy = str(year)[-2:]
    code = f"{base}{yy}{cat[:6]}"
    return code[:20]


def should_show_seasonal_campaign(holiday: Holiday, today: Optional[date] = None) -> bool:
    """
    Determine if a seasonal campaign should be shown.

    Shows campaigns within 42 days (6 weeks) of a holiday.

    Args:
        holiday: The holiday to check
        today: Reference date (defaults to today)

    Returns:
        True if campaign should be shown
    """
    if today is None:
        today = date.today()

    days_until = (holiday.date - today).days
    return 0 <= days_until <= 42
