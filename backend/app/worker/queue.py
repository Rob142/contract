"""PostgreSQL 작업 테이블을 큐로 쓴다 (설계서 5장).

- 획득: FOR UPDATE SKIP LOCKED로 대기 작업 하나를 원자적으로 가져오고 run_id를 새로 발급한다.
- 점유: heartbeat마다 lease_expires_at을 늘린다. 점유를 잃었거나 취소 요청이 있으면 알려준다.
- 회수: 점유가 만료된 작업은 남은 시도 횟수가 있으면 다시 대기열로, 없으면 실패로 둔다.
- 완료: 결과 저장은 run_id가 아직 내 것일 때만 한다. 늦게 끝난 작업자의 결과는 버린다.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    run_id: uuid.UUID
    kind: str
    owner_id: uuid.UUID
    contract_version_id: uuid.UUID
    attempts: int
    max_attempts: int
    started_at: datetime


class LeaseLostError(Exception):
    """다른 작업자에게 넘어갔거나 작업이 사라졌다."""


class JobCancelledError(Exception):
    pass


def claim_job(db: Session, kinds: list[str], lease_seconds: int) -> ClaimedJob | None:
    row = (
        db.execute(
            text(
                """
                UPDATE analysis_jobs j
                   SET status = 'running', run_id = :run_id, attempts = j.attempts + 1,
                       started_at = now(), heartbeat_at = now(),
                       lease_expires_at = now() + make_interval(secs => :lease),
                       stage = NULL, error_code = NULL, error_message = NULL
                 WHERE j.id = (
                       SELECT id FROM analysis_jobs
                        WHERE status = 'queued' AND kind = ANY(:kinds) AND cancel_requested_at IS NULL
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1)
                RETURNING j.id, j.run_id, j.kind, j.owner_id, j.contract_version_id,
                          j.attempts, j.max_attempts, j.started_at
                """
            ),
            {"run_id": uuid.uuid4(), "lease": lease_seconds, "kinds": kinds},
        )
        .mappings()
        .one_or_none()
    )
    db.commit()
    return ClaimedJob(**row) if row else None


def heartbeat(db: Session, job: ClaimedJob, stage: str | None, lease_seconds: int) -> None:
    row = db.execute(
        text(
            """
            UPDATE analysis_jobs
               SET heartbeat_at = now(), lease_expires_at = now() + make_interval(secs => :lease),
                   stage = COALESCE(:stage, stage)
             WHERE id = :id AND run_id = :run_id AND status = 'running'
            RETURNING cancel_requested_at
            """
        ),
        {"id": job.id, "run_id": job.run_id, "stage": stage, "lease": lease_seconds},
    ).one_or_none()
    db.commit()
    if row is None:
        raise LeaseLostError
    if row.cancel_requested_at is not None:
        raise JobCancelledError


def lock_own_job(db: Session, job: ClaimedJob) -> None:
    """결과 저장 트랜잭션 안에서 호출: 작업이 아직 내 것인지 확인하고 잠근다."""
    row = db.execute(
        text(
            """
            SELECT cancel_requested_at FROM analysis_jobs
             WHERE id = :id AND run_id = :run_id AND status = 'running'
             FOR UPDATE
            """
        ),
        {"id": job.id, "run_id": job.run_id},
    ).one_or_none()
    if row is None:
        raise LeaseLostError
    if row.cancel_requested_at is not None:
        raise JobCancelledError


def finish_job(
    db: Session, job: ClaimedJob, status: str, error_code: str | None = None, error: str | None = None
) -> bool:
    """내 run_id일 때만 종료 상태로 바꾼다. 바꿨으면 True."""
    result = db.execute(
        text(
            """
            UPDATE analysis_jobs
               SET status = :status, finished_at = now(), stage = NULL,
                   lease_expires_at = NULL, error_code = :code, error_message = :error
             WHERE id = :id AND run_id = :run_id AND status = 'running'
            """
        ),
        {"id": job.id, "run_id": job.run_id, "status": status, "code": error_code, "error": error},
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def requeue_job(db: Session, job: ClaimedJob, error_code: str, error: str) -> bool:
    """일시적 오류: 시도 횟수가 남았으면 다시 대기열로."""
    result = db.execute(
        text(
            """
            UPDATE analysis_jobs
               SET status = 'queued', run_id = NULL, lease_expires_at = NULL, stage = NULL,
                   error_code = :code, error_message = :error
             WHERE id = :id AND run_id = :run_id AND status = 'running' AND attempts < max_attempts
            """
        ),
        {"id": job.id, "run_id": job.run_id, "code": error_code, "error": error},
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def reap_expired(db: Session) -> int:
    """점유가 만료된 작업 회수. 시도 횟수를 다 쓴 추출 작업은 계약서 버전도 실패로 둔다."""
    rows = db.execute(
        text(
            """
            WITH expired AS (
              UPDATE analysis_jobs
                 SET status = CASE WHEN attempts < max_attempts THEN 'queued' ELSE 'failed' END,
                     finished_at = CASE WHEN attempts < max_attempts THEN NULL ELSE now() END,
                     run_id = NULL, lease_expires_at = NULL, stage = NULL,
                     error_code = 'lease_expired',
                     error_message = 'worker stopped responding'
               WHERE status = 'running' AND lease_expires_at < now()
              RETURNING id, status, kind, contract_version_id
            )
            , failed_extract AS (
              UPDATE contract_versions v
                 SET status = 'failed', failure_reason = 'worker_stopped'
                FROM expired e
               WHERE e.status = 'failed' AND e.kind = 'extract' AND v.id = e.contract_version_id
              RETURNING v.id
            ), failed_analyze AS (
              UPDATE contract_versions v
                 SET status = COALESCE(j.input->>'previous_status', 'ready')
                FROM expired e JOIN analysis_jobs j ON j.id = e.id
               WHERE e.status = 'failed' AND e.kind = 'analyze' AND v.id = e.contract_version_id
              RETURNING v.id
            )
            SELECT id FROM failed_extract UNION ALL SELECT id FROM failed_analyze
            """
        )
    ).all()
    db.commit()
    return len(rows)
