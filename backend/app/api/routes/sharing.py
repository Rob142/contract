"""프리랜서용: 공유 링크 관리, 피드백, 확인 기록, 수정 요청 카운터, 단계 템플릿."""

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.audit import record_audit
from app.core.clock import now_utc
from app.core.errors import AppError, not_found
from app.db.models import ExtraQuote, Project, RevisionRequest, TaskFeedback, User, ViewEvent
from app.db.session import get_db
from app.schemas.sharing import (
    ExtraQuoteIn,
    ExtraQuoteOut,
    FeedbackIn,
    FeedbackOut,
    JobTemplateOut,
    RevisionExcludeIn,
    RevisionState,
    ShareLinkOut,
    ShareLinkState,
    ShareLinkUpdate,
    ViewEventOut,
)
from app.services.projects import get_owned_project, get_owned_task
from app.services.sharing import active_link, create_link, link_out, recompute_over_limit, revision_state
from app.services.templates import JOB_TEMPLATES

router = APIRouter(tags=["sharing"])


@router.get("/job-templates", response_model=list[JobTemplateOut])
def job_templates(user: User = Depends(get_current_user)) -> list[JobTemplateOut]:
    return [JobTemplateOut(job_type=k, steps=v) for k, v in JOB_TEMPLATES.items()]  # type: ignore[arg-type]


# ---------------------------------------------------------------- 공유 링크
@router.get("/projects/{project_id}/share-link", response_model=ShareLinkState)
def read_share_link(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ShareLinkState:
    get_owned_project(db, user.id, project_id)
    link = active_link(db, project_id)
    return ShareLinkState(link=link_out(link) if link else None)


@router.post("/projects/{project_id}/share-link", status_code=201, response_model=ShareLinkOut)
def create_share_link(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ShareLinkOut:
    """토큰 원문은 이 응답에서만 볼 수 있다. 이미 링크가 있으면 재발급을 써야 한다."""
    project = get_owned_project(db, user.id, project_id, lock=True)
    if active_link(db, project.id) is not None:
        raise AppError(409, "share_link_exists", "a share link already exists; regenerate it instead")
    link, token = create_link(db, user.id, project.id)
    record_audit(
        db, actor_id=user.id, action="share_link.create", target_type="project", target_id=project.id
    )
    db.commit()
    db.refresh(link)
    return link_out(link, token)


@router.post("/projects/{project_id}/share-link/regenerate", status_code=201, response_model=ShareLinkOut)
def regenerate_share_link(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ShareLinkOut:
    project = get_owned_project(db, user.id, project_id, lock=True)
    old = active_link(db, project.id)
    show_invoices, allow_feedback = (old.show_invoices, old.allow_feedback) if old else (False, True)
    if old is not None:
        old.revoked_at = now_utc()
        db.flush()
    link, token = create_link(db, user.id, project.id)
    link.show_invoices, link.allow_feedback = show_invoices, allow_feedback
    record_audit(
        db, actor_id=user.id, action="share_link.regenerate", target_type="project", target_id=project.id
    )
    db.commit()
    db.refresh(link)
    return link_out(link, token)


@router.patch("/projects/{project_id}/share-link", response_model=ShareLinkOut)
def update_share_link(
    project_id: UUID,
    body: ShareLinkUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ShareLinkOut:
    get_owned_project(db, user.id, project_id)
    link = active_link(db, project_id)
    if link is None:
        raise not_found("share link")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(link, field, value)
    db.commit()
    db.refresh(link)
    return link_out(link)


@router.delete("/projects/{project_id}/share-link", status_code=204, response_class=Response)
def revoke_share_link(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    get_owned_project(db, user.id, project_id)
    link = active_link(db, project_id)
    if link is None:
        raise not_found("share link")
    link.revoked_at = now_utc()
    record_audit(
        db, actor_id=user.id, action="share_link.revoke", target_type="project", target_id=project_id
    )
    db.commit()


# ---------------------------------------------------------------- 피드백·확인 기록
@router.get("/projects/{project_id}/feedback", response_model=list[FeedbackOut])
def list_feedback(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TaskFeedback]:
    get_owned_project(db, user.id, project_id)
    return list(
        db.execute(
            select(TaskFeedback)
            .where(TaskFeedback.project_id == project_id)
            .order_by(TaskFeedback.created_at)
        ).scalars()
    )


@router.post("/tasks/{task_id}/feedback", status_code=201, response_model=FeedbackOut)
def add_feedback(
    task_id: UUID, body: FeedbackIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> TaskFeedback:
    task = get_owned_task(db, user.id, task_id)
    row = TaskFeedback(
        project_id=task.project_id,
        task_id=task.id,
        author_role="freelancer",
        author_name=user.issuer_name or user.name,
        body=body.body.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/projects/{project_id}/view-events", response_model=list[ViewEventOut])
def list_view_events(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ViewEvent]:
    get_owned_project(db, user.id, project_id)
    return list(
        db.execute(
            select(ViewEvent)
            .where(ViewEvent.project_id == project_id)
            .order_by(ViewEvent.created_at.desc())
            .limit(200)
        ).scalars()
    )


# ---------------------------------------------------------------- 수정 요청 카운터
@router.get("/projects/{project_id}/revisions", response_model=RevisionState)
def read_revisions(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RevisionState:
    return revision_state(db, get_owned_project(db, user.id, project_id))


def _owned_request(db: Session, owner_id: UUID, request_id: UUID) -> RevisionRequest:

    req = db.execute(
        select(RevisionRequest)
        .join(Project, Project.id == RevisionRequest.project_id)
        .where(RevisionRequest.id == request_id, Project.owner_id == owner_id)
    ).scalar_one_or_none()
    if req is None:
        raise not_found("revision request")
    return req


@router.post("/revision-requests/{request_id}/exclude", response_model=RevisionState)
def exclude_request(
    request_id: UUID,
    body: RevisionExcludeIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RevisionState:
    """카운트에서 뺀다(사유 필수). 요청 기록 자체는 남는다."""
    req = _owned_request(db, user.id, request_id)
    project = get_owned_project(db, user.id, req.project_id)
    if req.excluded_at is None:
        req.excluded_at = now_utc()
        req.excluded_reason = body.reason.strip()
        recompute_over_limit(db, project)
        record_audit(
            db,
            actor_id=user.id,
            action="revision_request.exclude",
            target_type="revision_request",
            target_id=req.id,
        )
        db.commit()
    return revision_state(db, project)


@router.post("/projects/{project_id}/extra-quotes", status_code=201, response_model=ExtraQuoteOut)
def create_extra_quote(
    project_id: UUID,
    body: ExtraQuoteIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ExtraQuote:
    get_owned_project(db, user.id, project_id)
    if body.revision_request_id is not None:
        if _owned_request(db, user.id, body.revision_request_id).project_id != project_id:
            raise not_found("revision request")
    quote = ExtraQuote(
        owner_id=user.id,
        project_id=project_id,
        revision_request_id=body.revision_request_id,
        title=body.title.strip(),
        description=(body.description or "").strip() or None,
        amount=body.amount,
    )
    db.add(quote)
    db.commit()
    db.refresh(quote)
    return quote
