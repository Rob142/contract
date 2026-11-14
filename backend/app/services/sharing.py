"""공유 링크, 수정 요청 카운터, 클라이언트 공개 응답 조립.

공개 응답은 허용 목록 방식이다. 단가·메모·계약서 원문·거래처 연락처 같은 내부 정보는 여기서 만들지 않는다.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.clock import now_utc
from app.core.errors import AppError, not_found
from app.core.security import new_session_token, token_digest
from app.db.models import (
    Attachment,
    ExtraQuote,
    Project,
    RevisionRequest,
    ShareLink,
    StoredFile,
    Task,
    TaskFeedback,
    User,
    ViewEvent,
)
from app.schemas.sharing import (
    ExtraQuoteOut,
    FeedbackOut,
    PublicAttachment,
    PublicContract,
    PublicInvoice,
    PublicProject,
    PublicTask,
    RevisionCounter,
    RevisionRequestOut,
    RevisionState,
    ShareLinkOut,
)

DEFAULT_CLIENT_NAME = "클라이언트"


# ---------------------------------------------------------------- 공유 링크
def active_link(db: Session, project_id: UUID) -> ShareLink | None:
    return db.execute(
        select(ShareLink).where(ShareLink.project_id == project_id, ShareLink.revoked_at.is_(None))
    ).scalar_one_or_none()


def create_link(db: Session, owner_id: UUID, project_id: UUID) -> tuple[ShareLink, str]:
    token = new_session_token()
    link = ShareLink(owner_id=owner_id, project_id=project_id, token_hash=token_digest(token))
    db.add(link)
    db.flush()
    return link, token


def link_out(link: ShareLink, token: str | None = None) -> ShareLinkOut:
    return ShareLinkOut(
        id=link.id,
        token=token,
        expires_at=link.expires_at,
        show_invoices=link.show_invoices,
        allow_feedback=link.allow_feedback,
        last_viewed_at=link.last_viewed_at,
        created_at=link.created_at,
    )


def resolve_link(db: Session, token: str) -> ShareLink:
    """없음·폐기·만료를 모두 같은 404로 돌려 링크의 존재 여부를 알려 주지 않는다."""
    link = db.execute(
        select(ShareLink).where(ShareLink.token_hash == token_digest(token))
    ).scalar_one_or_none()
    if (
        link is None
        or link.revoked_at is not None
        or (link.expires_at is not None and link.expires_at <= now_utc())
    ):
        raise not_found("share link")
    return link


# ---------------------------------------------------------------- 수정 요청 카운터
def revision_counter(db: Session, project: Project) -> RevisionCounter:
    used = db.execute(
        select(func.count())
        .select_from(RevisionRequest)
        .where(RevisionRequest.project_id == project.id, RevisionRequest.excluded_at.is_(None))
    ).scalar_one()
    included = project.included_revisions
    return RevisionCounter(
        included=included, used=used, remaining=None if included is None else max(included - used, 0)
    )


def add_revision_request(
    db: Session, project_id: UUID, body: str, requester_name: str, task_id: UUID | None
) -> RevisionRequest:
    """프로젝트 행을 잠근 뒤 회차를 매겨 동시 요청에도 회차가 겹치지 않게 한다."""
    project = db.execute(select(Project).where(Project.id == project_id).with_for_update()).scalar_one()
    if (
        task_id is not None
        and db.execute(select(Task.id).where(Task.id == task_id, Task.project_id == project_id)).first()
        is None
    ):
        raise not_found("task")
    seq = (
        db.execute(
            select(func.coalesce(func.max(RevisionRequest.seq), 0)).where(
                RevisionRequest.project_id == project_id
            )
        ).scalar_one()
        + 1
    )
    counter = revision_counter(db, project)
    over = counter.included is not None and counter.used >= counter.included
    request = RevisionRequest(
        project_id=project_id,
        task_id=task_id,
        seq=seq,
        body=body.strip(),
        requester_name=requester_name,
        over_limit=over,
    )
    db.add(request)
    db.flush()
    return request


def recompute_over_limit(db: Session, project: Project) -> None:
    """카운트에서 제외한 요청이 생기면 초과 표시를 순서대로 다시 매긴다.

    제외되지 않은 요청을 회차 순으로 세어, 포함 횟수를 넘는 것만 초과로 표시한다.
    """
    requests = (
        db.execute(
            select(RevisionRequest)
            .where(RevisionRequest.project_id == project.id)
            .order_by(RevisionRequest.seq)
        )
        .scalars()
        .all()
    )
    counted = 0
    for r in requests:
        if r.excluded_at is not None:
            r.over_limit = False
            continue
        counted += 1
        r.over_limit = project.included_revisions is not None and counted > project.included_revisions
    db.flush()


def revision_state(db: Session, project: Project) -> RevisionState:
    requests = (
        db.execute(
            select(RevisionRequest)
            .where(RevisionRequest.project_id == project.id)
            .order_by(RevisionRequest.seq)
        )
        .scalars()
        .all()
    )
    quotes = (
        db.execute(
            select(ExtraQuote).where(ExtraQuote.project_id == project.id).order_by(ExtraQuote.created_at)
        )
        .scalars()
        .all()
    )
    return RevisionState(
        counter=revision_counter(db, project),
        requests=[RevisionRequestOut.model_validate(r) for r in requests],
        quotes=[ExtraQuoteOut.model_validate(q) for q in quotes],
    )


# ---------------------------------------------------------------- 공개 응답
def build_public_project(db: Session, link: ShareLink) -> PublicProject:
    project = db.get(Project, link.project_id)
    owner = db.get(User, link.owner_id)
    if project is None or owner is None:
        raise not_found("share link")

    tasks = (
        db.execute(select(Task).where(Task.project_id == project.id).order_by(Task.position)).scalars().all()
    )
    deliverables = db.execute(
        select(Attachment, StoredFile.id.label("fid"))
        .outerjoin(StoredFile, StoredFile.id == Attachment.file_id)
        .where(Attachment.project_id == project.id, Attachment.kind == "deliverable")
        .order_by(Attachment.created_at)
    ).all()
    feedback = (
        db.execute(
            select(TaskFeedback)
            .where(TaskFeedback.project_id == project.id)
            .order_by(TaskFeedback.created_at)
        )
        .scalars()
        .all()
    )
    ack_rows = db.execute(
        select(ViewEvent.task_id, func.max(ViewEvent.created_at))
        .where(
            ViewEvent.share_link_id == link.id, ViewEvent.kind == "stage_ack", ViewEvent.task_id.is_not(None)
        )
        .group_by(ViewEvent.task_id)
    ).all()
    acks: dict[UUID | None, datetime] = {task_id: seen for task_id, seen in ack_rows}
    revision_requests = (
        db.execute(
            select(RevisionRequest)
            .where(RevisionRequest.project_id == project.id)
            .order_by(RevisionRequest.seq)
        )
        .scalars()
        .all()
    )

    public_tasks = []
    for t in tasks:
        public_tasks.append(
            PublicTask(
                id=t.id,
                title=t.title,
                status=t.status,  # type: ignore[arg-type]
                due_date=t.due_date,
                completed_at=t.completed_at,
                deliverables=[
                    PublicAttachment(
                        id=a.id,
                        title=a.title,
                        url=a.url,
                        has_file=a.file_id is not None,
                        created_at=a.created_at,
                    )
                    for a, _fid in deliverables
                    if a.task_id == t.id
                ],
                feedback=[FeedbackOut.model_validate(f) for f in feedback if f.task_id == t.id],
                acknowledged_at=acks.get(t.id),
            )
        )

    done = sum(1 for t in tasks if t.status == "done")
    invoices: list[PublicInvoice] | None = None
    if link.show_invoices:
        rows = db.execute(
            text(
                """
                SELECT b.invoice_no, b.total, b.due_date, b.payment_status
                  FROM v_invoice_balances b
                 WHERE b.project_id = :pid AND b.status = 'issued'
                 ORDER BY b.due_date NULLS LAST, b.invoice_no
                """
            ),
            {"pid": project.id},
        ).mappings()
        invoices = [
            PublicInvoice(
                invoice_no=r["invoice_no"],
                total=r["total"],
                due_date=r["due_date"],
                status="paid" if r["payment_status"] == "paid" else "issued",
            )
            for r in rows
        ]

    return PublicProject(
        name=project.name,
        job_type=project.job_type,  # type: ignore[arg-type]
        progress_pct=round(done * 100 / len(tasks)) if tasks else None,
        freelancer_name=owner.issuer_name or owner.name,
        contract=PublicContract(
            contract_amount=project.contract_amount,
            start_date=project.start_date,
            due_date=project.due_date,
            included_revisions=project.included_revisions,
        ),
        revision=revision_counter(db, project),
        allow_feedback=link.allow_feedback,
        tasks=public_tasks,
        invoices=invoices,
        revision_requests=[RevisionRequestOut.model_validate(r) for r in revision_requests],
    )


def clean_name(value: str | None) -> str:
    return (value or "").strip() or DEFAULT_CLIENT_NAME


def touch_link(
    db: Session, link: ShareLink, kind: str, viewer: str | None, task_id: UUID | None = None
) -> None:
    db.add(
        ViewEvent(
            share_link_id=link.id,
            project_id=link.project_id,
            task_id=task_id,
            kind=kind,
            viewer_name=(viewer or "").strip() or None,
        )
    )
    link.last_viewed_at = now_utc()


def require_feedback_allowed(link: ShareLink) -> None:
    if not link.allow_feedback:
        raise AppError(403, "feedback_disabled", "feedback is turned off for this link")
