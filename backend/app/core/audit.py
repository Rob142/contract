"""중요 상태 변경 감사 기록 (발행·취소·입금·삭제·확인값 변경).

summary에는 식별자·금액·상태 같은 요약만 넣는다. 계약서 본문·개인정보·API 키는 금지.
호출한 쪽의 트랜잭션에 함께 커밋된다.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record_audit(
    db: Session,
    *,
    actor_id: UUID | None,
    action: str,
    target_type: str,
    target_id: UUID,
    **summary: Any,
) -> None:
    db.add(
        AuditEvent(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            summary={k: str(v) if isinstance(v, UUID) else v for k, v in summary.items()},
        )
    )
