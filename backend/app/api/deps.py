from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.security import token_digest
from app.db.models import User, UserSession
from app.db.session import get_db


def get_session_token(request: Request) -> str | None:
    return request.cookies.get(get_settings().session_cookie_name)


def get_current_session(
    token: str | None = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> UserSession:
    if not token:
        raise AppError(401, "not_authenticated", "login required")
    session = db.execute(
        select(UserSession).where(
            UserSession.token_hash == token_digest(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > datetime.now(UTC),
        )
    ).scalar_one_or_none()
    if session is None:
        raise AppError(401, "not_authenticated", "session expired or invalid")
    return session


def get_current_user(
    session: UserSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, session.user_id)
    if user is None:
        raise AppError(401, "not_authenticated", "session expired or invalid")
    return user


def get_owned_or_404[ModelT](
    db: Session, model: type[ModelT], obj_id: UUID, owner_id: UUID, what: str
) -> ModelT:
    """owner_id 컬럼이 있는 리소스 조회. 남의 것이면 404 (존재 비노출).

    owner_id가 없는 하위 엔터티(작업, 청구 항목 등)는 부모와 조인해 같은 방식으로 검사한다.
    """
    model_any: Any = model
    obj = db.execute(
        select(model).where(model_any.id == obj_id, model_any.owner_id == owner_id)
    ).scalar_one_or_none()
    if obj is None:
        raise not_found(what)
    return obj
