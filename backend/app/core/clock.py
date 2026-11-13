from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def now_utc() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().timezone)).date()


def week_range(day: date) -> tuple[date, date]:
    """월요일~일요일"""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def month_range(day: date) -> tuple[date, date]:
    """이번 달 1일 ~ 다음 달 1일 (끝은 포함하지 않음)"""
    start = day.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    return start, end
