"""가입 없는 클라이언트용 공개 API. 인증 의존성을 쓰지 않고 공유 링크 토큰만으로 접근한다.

응답은 services.sharing의 허용 목록 스키마만 쓴다. 토큰이 없거나 폐기·만료되면 모두 404다.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes.attachments import stream_file
from app.core.errors import AppError, not_found
from app.core.rate_limit import SlidingWindowLimiter
from app.core.storage import FileStorage, get_storage
from app.db.models import Attachment, ShareLink, StoredFile, Task, TaskFeedback
from app.db.session import get_db
from app.schemas.sharing import (
    AckIn,
    FeedbackIn,
    FeedbackOut,
    PublicProject,
    RevisionRequestIn,
    RevisionRequestOut,
)
from app.services.sharing import (
    add_revision_request,
    build_public_project,
    clean_name,
    require_feedback_allowed,
    resolve_link,
    touch_link,
)


def public_headers(response: Response) -> None:
    """토큰이 주소에 있으므로 검색엔진·캐시·리퍼러로 새지 않게 한다."""
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/public/p/{token}", tags=["public"], dependencies=[Depends(public_headers)])

_write_limiter = SlidingWindowLimiter(max_attempts=30, window_seconds=60)


def get_write_limiter() -> SlidingWindowLimiter:
    return _write_limiter


def limit_writes(request: Request, token: str) -> None:
    """쓰기 요청은 링크·IP별로 분당 횟수를 제한한다."""
    ip = request.client.host if request.client else "unknown"
    key = f"{ip}|{token[:12]}"
    limiter = get_write_limiter()
    if limiter.is_blocked(key):
        raise AppError(429, "too_many_requests", "too many requests; try again later")
    limiter.record_failure(key)


def _link(token: str, db: Session) -> ShareLink:
    return resolve_link(db, token)


def _task_of(db: Session, link: ShareLink, task_id: UUID) -> Task:
    task = db.execute(
        select(Task).where(Task.id == task_id, Task.project_id == link.project_id)
    ).scalar_one_or_none()
    if task is None:
        raise not_found("task")
    return task


@router.get("", response_model=PublicProject)
def read_project(
    token: str, record: bool = Query(default=True), db: Session = Depends(get_db)
) -> PublicProject:
    link = _link(token, db)
    if record:
        touch_link(db, link, "open", None)
        db.commit()
    return build_public_project(db, link)


@router.post("/tasks/{task_id}/ack", status_code=204)
def acknowledge_task(
    token: str, task_id: UUID, body: AckIn, request: Request, db: Session = Depends(get_db)
) -> None:
    limit_writes(request, token)
    link = _link(token, db)
    _task_of(db, link, task_id)
    touch_link(db, link, "stage_ack", body.viewer_name, task_id)
    db.commit()


@router.post("/tasks/{task_id}/feedback", status_code=201, response_model=FeedbackOut)
def add_feedback(
    token: str, task_id: UUID, body: FeedbackIn, request: Request, db: Session = Depends(get_db)
) -> TaskFeedback:
    limit_writes(request, token)
    link = _link(token, db)
    require_feedback_allowed(link)
    task = _task_of(db, link, task_id)
    row = TaskFeedback(
        project_id=link.project_id,
        task_id=task.id,
        author_role="client",
        author_name=clean_name(body.author_name),
        body=body.body.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/revision-requests", status_code=201, response_model=RevisionRequestOut)
def request_revision(
    token: str, body: RevisionRequestIn, request: Request, db: Session = Depends(get_db)
) -> RevisionRequestOut:
    """수정 요청을 받는다. 포함 횟수를 넘겨도 기록은 받고 over_limit만 표시한다."""
    limit_writes(request, token)
    link = _link(token, db)
    require_feedback_allowed(link)
    row = add_revision_request(db, link.project_id, body.body, clean_name(body.requester_name), body.task_id)
    db.commit()
    db.refresh(row)
    return RevisionRequestOut.model_validate(row)


@router.get("/attachments/{attachment_id}/file", response_class=StreamingResponse)
def download_deliverable(
    token: str,
    attachment_id: UUID,
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> StreamingResponse:
    """결과물 파일만 내려받을 수 있다. 증빙·기타 첨부는 클라이언트에게 열지 않는다."""
    link = _link(token, db)
    att = db.execute(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.project_id == link.project_id,
            Attachment.kind == "deliverable",
        )
    ).scalar_one_or_none()
    stored = db.get(StoredFile, att.file_id) if att and att.file_id else None
    if stored is None:
        raise not_found("file")
    touch_link(db, link, "deliverable", None)
    db.commit()
    return stream_file(stored, storage, download=True)
