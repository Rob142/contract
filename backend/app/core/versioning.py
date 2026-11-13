"""낙관적 잠금: 클라이언트가 읽은 시점의 updated_at을 보내고, 그 사이 바뀌었으면 409."""

from datetime import datetime

from app.core.errors import conflict


def assert_version(current: datetime, expected: datetime | None) -> None:
    if expected is not None and current != expected:
        raise conflict(
            "version_conflict",
            "the resource was changed by another request; reload and try again",
            {"current_version": current.isoformat()},
        )
