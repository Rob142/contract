import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_session_token
from app.core.errors import AppError
from app.core.security import hash_password, token_digest, verify_password
from app.db.models import User, UserSession
from app.db.session import get_db
from app.schemas.users import LlmModelCreate, PasswordChangeIn, UserOut, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])

# null로 비울 수 없는 필드
_REQUIRED_FIELDS = {"name", "job_type", "default_llm_mode", "preferred_mode"}


def _sync_active_llm_fields(user: User) -> None:
    """llm_models 목록에서 모드별 활성 모델을 기존 컬럼과 동기화한다."""
    models = [dict(m) for m in (user.llm_models or []) if isinstance(m, dict)]
    for mode, prefix in (("commercial", "commercial_llm"), ("local", "local_llm")):
        mode_items = [m for m in models if m.get("mode") == mode]
        active = next((m for m in mode_items if m.get("is_active")), mode_items[0] if mode_items else None)
        if active is not None:
            for m in models:
                if m.get("mode") == mode:
                    m["is_active"] = m.get("id") == active.get("id")
            setattr(user, f"{prefix}_model", active.get("model"))
            setattr(user, f"{prefix}_api_base", active.get("api_base"))
            setattr(user, f"{prefix}_api_key", active.get("api_key"))
        else:
            setattr(user, f"{prefix}_model", None)
            setattr(user, f"{prefix}_api_base", None)
            setattr(user, f"{prefix}_api_key", None)
    user.llm_models = models


@router.get("/me", response_model=UserOut)
def read_me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/me/llm-models", response_model=UserOut, status_code=201)
def add_llm_model(
    body: LlmModelCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    model_str = body.model.strip()
    if not model_str:
        raise AppError(422, "validation_error", "model is required", {"fields": ["model"]})
    api_base = (body.api_base or "").strip() or None
    api_key = (body.api_key or "").strip() or None

    existing = [dict(m) for m in (user.llm_models or []) if isinstance(m, dict)]
    for m in existing:
        if m.get("mode") == body.mode:
            m["is_active"] = False
    new_item = {
        "id": str(uuid.uuid4()),
        "mode": body.mode,
        "model": model_str,
        "api_base": api_base,
        "api_key": api_key,
        "is_active": True,
    }
    existing.append(new_item)
    user.llm_models = existing
    _sync_active_llm_fields(user)
    if user.default_llm_mode == "ask":
        user.default_llm_mode = body.mode
    db.commit()
    return user


@router.patch("/me/llm-models/{model_id}/activate", response_model=UserOut)
def activate_llm_model(
    model_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    existing = [dict(m) for m in (user.llm_models or []) if isinstance(m, dict)]
    target = next((m for m in existing if m.get("id") == model_id), None)
    if target is None:
        raise AppError(404, "not_found", "model not found")
    mode = target.get("mode")
    for m in existing:
        if m.get("mode") == mode:
            m["is_active"] = m.get("id") == model_id
    user.llm_models = existing
    _sync_active_llm_fields(user)
    db.commit()
    return user


@router.delete("/me/llm-models/{model_id}", response_model=UserOut)
def delete_llm_model(
    model_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    existing = [dict(m) for m in (user.llm_models or []) if isinstance(m, dict)]
    next_models = [m for m in existing if m.get("id") != model_id]
    if len(next_models) == len(existing):
        raise AppError(404, "not_found", "model not found")
    user.llm_models = next_models
    _sync_active_llm_fields(user)
    db.commit()
    return user


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    changes = body.model_dump(exclude_unset=True)
    cleared = sorted(k for k, v in changes.items() if v is None and k in _REQUIRED_FIELDS)
    if cleared:
        raise AppError(422, "validation_error", "these fields cannot be empty", {"fields": cleared})
    for field, value in changes.items():
        if isinstance(value, str):
            stripped = value.strip()
            setattr(user, field, stripped or None if field not in _REQUIRED_FIELDS else stripped)
        else:
            setattr(user, field, value)
    db.commit()
    return user


@router.patch("/me/password", status_code=204)
def change_password(
    body: PasswordChangeIn,
    user: User = Depends(get_current_user),
    current_token: str | None = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> None:
    """비밀번호 변경. 현재 비밀번호를 확인하고, 이 요청에 쓴 세션만 남긴 채 다른 세션은 무효화한다."""
    if not verify_password(user.password_hash, body.current_password):
        raise AppError(422, "wrong_password", "the current password is incorrect")
    if body.current_password == body.new_password:
        raise AppError(422, "same_password", "the new password must be different from the current one")

    user.password_hash = hash_password(body.new_password)
    if current_token:
        db.execute(
            update(UserSession)
            .where(
                UserSession.user_id == user.id,
                UserSession.token_hash != token_digest(current_token),
                UserSession.revoked_at.is_(None),
            )
            .values(revoked_at=func.now())
        )
    db.commit()
