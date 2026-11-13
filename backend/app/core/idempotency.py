"""재전송 키 (Idempotency-Key): 발행·입금·프로젝트 확정처럼 두 번 실행되면 안 되는 요청에 쓴다.

같은 키 + 같은 요청 → 처음 응답을 그대로 돌려준다.
같은 키 + 다른 요청 → 409.
키 예약과 실제 작업이 같은 트랜잭션이라, 작업이 실패해 롤백되면 같은 키로 재시도할 수 있다.
동시에 같은 키가 오면 두 번째 요청은 첫 요청이 커밋될 때까지 기다린 뒤 저장된 응답을 받는다.

사용법 (호출한 쪽이 커밋한다):
    status, body = run_idempotent(db, user.id, key, payload, lambda: (201, create_something()))
    db.commit()
"""

import hashlib
import json
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import Header
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError, conflict
from app.db.models import IdempotencyKey


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if not idempotency_key or not 8 <= len(idempotency_key) <= 128:
        raise AppError(428, "idempotency_key_required", "Idempotency-Key header (8-128 chars) is required")
    return idempotency_key


def request_fingerprint(payload: Any) -> str:
    canonical = json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def run_idempotent(
    db: Session,
    owner_id: UUID,
    key: str,
    payload: Any,
    handler: Callable[[], tuple[int, Any]],
) -> tuple[int, Any]:
    fingerprint = request_fingerprint(payload)

    reserved = db.execute(
        insert(IdempotencyKey)
        .values(owner_id=owner_id, key=key, request_hash=fingerprint)
        .on_conflict_do_nothing(index_elements=["owner_id", "key"])
        .returning(IdempotencyKey.key)
    ).first()

    if reserved is None:
        existing = db.execute(
            select(IdempotencyKey)
            .where(IdempotencyKey.owner_id == owner_id, IdempotencyKey.key == key)
            .with_for_update()
        ).scalar_one()
        if existing.request_hash != fingerprint:
            raise conflict("idempotency_key_reused", "this Idempotency-Key was used for a different request")
        if existing.response_status is None:
            raise conflict("request_in_progress", "a request with this Idempotency-Key is still running")
        return existing.response_status, existing.response_body

    status, body = handler()
    db.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.owner_id == owner_id, IdempotencyKey.key == key)
        .values(response_status=status, response_body=jsonable_encoder(body))
    )
    return status, body
