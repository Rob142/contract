from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_session_token
from app.core.config import get_settings
from app.core.errors import AppError, conflict
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import (
    hash_password,
    new_session_token,
    password_needs_rehash,
    token_digest,
    verify_password,
)
from app.db.models import User, UserSession
from app.db.session import get_db
from app.schemas.users import LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@lru_cache
def get_login_limiter() -> SlidingWindowLimiter:
    settings = get_settings()
    return SlidingWindowLimiter(settings.login_max_attempts, settings.login_window_seconds)


def _start_session(db: Session, response: Response, request: Request, user: User, remember: bool) -> None:
    settings = get_settings()
    lifetime = (
        timedelta(days=settings.session_remember_days)
        if remember
        else timedelta(hours=settings.session_ttl_hours)
    )
    token = new_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=token_digest(token),
            expires_at=datetime.now(UTC) + lifetime,
            user_agent=(request.headers.get("user-agent") or "")[:300] or None,
        )
    )
    response.set_cookie(
        settings.session_cookie_name,
        token,
        # "로그인 상태 유지"가 아니면 브라우저 세션 쿠키 (서버 만료는 별도로 적용)
        max_age=int(lifetime.total_seconds()) if remember else None,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=201, response_model=UserOut)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    if not body.agree_terms:
        raise AppError(422, "terms_not_agreed", "terms and privacy policy must be accepted")

    email = body.email.lower()
    if db.execute(select(User.id).where(func.lower(User.email) == email)).first():
        raise conflict("email_taken", "this email is already registered")

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name.strip(),
        job_type=body.job_type,
        preferred_mode=body.preferred_mode,
        issuer_name=body.name.strip(),
        issuer_contact=email,
        terms_agreed_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    _start_session(db, response, request, user, remember=False)
    db.commit()
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    email = body.email.lower()
    client_ip = request.client.host if request.client else "unknown"
    limiter = get_login_limiter()
    limit_key = f"{client_ip}|{email}"
    if limiter.is_blocked(limit_key):
        raise AppError(429, "too_many_attempts", "too many failed logins; try again later")

    user = db.execute(select(User).where(func.lower(User.email) == email)).scalar_one_or_none()
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        limiter.record_failure(limit_key)
        raise AppError(401, "invalid_credentials", "email or password is incorrect")

    limiter.reset(limit_key)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    _start_session(db, response, request, user, remember=body.remember)
    db.commit()
    return user


@router.post("/logout", status_code=204)
def logout(
    response: Response, token: str | None = Depends(get_session_token), db: Session = Depends(get_db)
) -> None:
    if token:
        db.execute(
            update(UserSession)
            .where(UserSession.token_hash == token_digest(token), UserSession.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        db.commit()
    settings = get_settings()
    response.delete_cookie(
        settings.session_cookie_name, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
    )
