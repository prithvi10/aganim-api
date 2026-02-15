"""
Holiday Detection Logic for Seasonal Marketing

Provides utilities for detecting upcoming holidays and generating
seasonal campaign data. Moved from agent_actions.py.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional
import re


@dataclass(frozen=True)
class Holiday:
    """Represents a holiday with name and date."""
    name: str
    date: date


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


def get_us_holidays_for_year(year: int) -> list[Holiday]:
    """
    Get all major US holidays for a given year.
    
    Includes both fixed-date holidays (Christmas, Valentine's, etc.)
    and floating holidays (Thanksgiving, Mother's Day, etc.).
    
    Args:
        year: Year to get holidays for
    
    Returns:
        List of Holiday objects
    """
    # Floating holidays
    thanksgiving = _nth_weekday_of_month(year, 11, weekday=3, n=4)  # 4th Thursday
    black_friday = thanksgiving + timedelta(days=1)
    cyber_monday = thanksgiving + timedelta(days=4)
    mothers_day = _nth_weekday_of_month(year, 5, weekday=6, n=2)  # 2nd Sunday
    fathers_day = _nth_weekday_of_month(year, 6, weekday=6, n=3)  # 3rd Sunday
    memorial_day = _last_weekday_of_month(year, 5, weekday=0)     # Last Monday
    labor_day = _nth_weekday_of_month(year, 9, weekday=0, n=1)    # 1st Monday

    fixed = [
        Holiday("New Year's Day", date(year, 1, 1)),
        Holiday("Valentine's Day", date(year, 2, 14)),
        Holiday("Independence Day", date(year, 7, 4)),
        Holiday("Halloween", date(year, 10, 31)),
        Holiday("Christmas", date(year, 12, 25)),
    ]
    
    floating = [
        Holiday("Mother's Day", mothers_day),
        Holiday("Memorial Day", memorial_day),
        Holiday("Father's Day", fathers_day),
        Holiday("Labor Day", labor_day),
        Holiday("Thanksgiving", thanksgiving),
        Holiday("Black Friday", black_friday),
        Holiday("Cyber Monday", cyber_monday),
    ]
    
    return fixed + floating


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
    
    # Get holidays for this year and next
    candidates = (
        get_us_holidays_for_year(today.year) + 
        get_us_holidays_for_year(today.year + 1)
    )
    
    # Filter to upcoming only
    candidates = [h for h in candidates if h.date >= today]
    candidates.sort(key=lambda h: h.date)
    
    return candidates[0] if candidates else None


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
