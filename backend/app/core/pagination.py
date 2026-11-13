"""목록 페이지 처리. 커서는 불투명 문자열로 주고받는다(현재는 오프셋을 인코딩)."""

import base64
import binascii

from fastapi import Query
from pydantic import BaseModel

from app.core.errors import AppError


class PageParams(BaseModel):
    limit: int
    offset: int


def page_params(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=64),
) -> PageParams:
    return PageParams(limit=limit, offset=decode_cursor(cursor) if cursor else 0)


def encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"o:{offset}".encode()).decode()


def decode_cursor(cursor: str) -> int:
    try:
        prefix, value = base64.urlsafe_b64decode(cursor.encode()).decode().split(":", 1)
        offset = int(value)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise AppError(422, "invalid_cursor", "cursor is invalid") from exc
    if prefix != "o" or offset < 0:
        raise AppError(422, "invalid_cursor", "cursor is invalid")
    return offset


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None


def build_page[T](rows: list[T], params: PageParams) -> Page[T]:
    """rows는 limit + 1개까지 조회한 결과. 남는 한 건이 있으면 다음 커서를 만든다."""
    has_more = len(rows) > params.limit
    return Page[T](
        items=rows[: params.limit],
        next_cursor=encode_cursor(params.offset + params.limit) if has_more else None,
    )
