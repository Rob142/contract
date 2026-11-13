from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import now_utc
from app.core.errors import conflict, not_found
from app.db.models import AnalysisJob, ContractVersion, User
from app.db.session import get_db
from app.schemas.contracts import JobOut
from app.services.contracts import job_out

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _owned_job(db: Session, owner_id: UUID, job_id: UUID, *, lock: bool = False) -> AnalysisJob:
    stmt = select(AnalysisJob).where(AnalysisJob.id == job_id, AnalysisJob.owner_id == owner_id)
    if lock:
        stmt = stmt.with_for_update()
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        raise not_found("job")
    return job


@router.get("/{job_id}", response_model=JobOut)
def read_job(job_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobOut:
    return job_out(_owned_job(db, user.id, job_id))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobOut:
    """대기 중이면 바로 취소, 실행 중이면 취소를 요청하고 작업자가 다음 단계에서 멈춘다."""
    job = _owned_job(db, user.id, job_id, lock=True)
    if job.status not in ("queued", "running"):
        raise conflict("job_finished", "the job has already finished")

    job.cancel_requested_at = job.cancel_requested_at or now_utc()
    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = now_utc()
        if job.kind == "extract":
            version = db.get(ContractVersion, job.contract_version_id)
            if version is not None:
                version.status = "failed"
                version.failure_reason = "cancelled"
    db.commit()
    db.refresh(job)
    return job_out(job)
