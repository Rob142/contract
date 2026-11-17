"""Client tenant authorization and allow-listed project serialization."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, not_found
from app.db.models import (
    ClientDelivery,
    ClientDeliveryVersion,
    ClientExtraAcceptance,
    ClientInquiry,
    ClientProjectLink,
    ClientProjectMember,
    ClientQuoteVersion,
    ClientReviewEvent,
    ExtraQuote,
    Project,
    Task,
    User,
    WorkspaceMember,
)
from app.services.sharing import revision_counter


def member(db: Session, workspace_id: UUID, user_id: UUID, manage: bool = False) -> WorkspaceMember:
    row = db.scalar(
        select(WorkspaceMember)
        .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        .with_for_update()
    )
    if row is None or (manage and row.role not in ("owner", "admin")):
        raise not_found("workspace")
    return row


def project_access(
    db: Session, project_id: UUID, user_id: UUID, write: bool = False, finance: bool = False
) -> tuple[Project, ClientProjectLink | None, WorkspaceMember | None]:
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("project")
    if project.owner_id == user_id:
        return (
            project,
            db.scalar(select(ClientProjectLink).where(ClientProjectLink.project_id == project_id)),
            None,
        )
    link = db.scalar(select(ClientProjectLink).where(ClientProjectLink.project_id == project_id))
    if link is None:
        raise not_found("project")
    m = member(db, link.workspace_id, user_id)
    grant = db.scalar(
        select(ClientProjectMember).where(
            ClientProjectMember.link_id == link.id, ClientProjectMember.user_id == user_id
        )
    )
    if grant is None or (write and m.role == "viewer") or (finance and not grant.can_finance):
        raise not_found("project")
    return project, link, m


def visible_projects(db: Session, workspace_id: UUID, user_id: UUID) -> list[Project]:
    member(db, workspace_id, user_id)
    return list(
        db.scalars(
            select(Project)
            .join(ClientProjectLink)
            .join(ClientProjectMember, ClientProjectMember.link_id == ClientProjectLink.id)
            .where(ClientProjectLink.workspace_id == workspace_id, ClientProjectMember.user_id == user_id)
            .order_by(Project.created_at.desc())
        )
    )


def versions_out(db: Session, project_id: UUID) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    deliveries = db.scalars(
        select(ClientDelivery)
        .where(ClientDelivery.project_id == project_id)
        .order_by(ClientDelivery.created_at)
    )
    for d in deliveries:
        versions = list(
            db.scalars(
                select(ClientDeliveryVersion)
                .where(ClientDeliveryVersion.delivery_id == d.id)
                .order_by(ClientDeliveryVersion.seq)
            )
        )
        for v in versions:
            events = list(
                db.scalars(
                    select(ClientReviewEvent)
                    .where(ClientReviewEvent.version_id == v.id)
                    .order_by(ClientReviewEvent.created_at)
                )
            )
            decision = next((e.kind for e in events if e.kind in ("approved", "changes")), "pending")
            rows.append(
                dict(
                    id=v.id,
                    delivery_id=d.id,
                    title=d.title,
                    seq=v.seq,
                    payload=v.payload,
                    due_date=v.due_date,
                    created_at=v.created_at,
                    current=v.seq == versions[-1].seq,
                    state=decision,
                    events=[
                        dict(
                            id=e.id,
                            kind=e.kind,
                            body=e.body,
                            actor_name=e.actor_name,
                            workspace_name=e.workspace_name,
                            created_at=e.created_at,
                        )
                        for e in events
                    ],
                )
            )
    return rows


def project_out(db: Session, project_id: UUID, user_id: UUID) -> dict[str, Any]:
    p, link, m = project_access(db, project_id, user_id)
    owner = p.owner_id == user_id
    grant = (
        db.scalar(
            select(ClientProjectMember).where(
                ClientProjectMember.link_id == link.id, ClientProjectMember.user_id == user_id
            )
        )
        if link
        else None
    )
    finance = owner or bool(grant and grant.can_finance)
    tasks = db.scalars(select(Task).where(Task.project_id == p.id).order_by(Task.due_date, Task.position))
    extras = list(db.scalars(select(ExtraQuote).where(ExtraQuote.project_id == p.id))) if finance else []
    quote = (
        db.scalar(
            select(ClientQuoteVersion)
            .join(ClientInquiry)
            .where(ClientInquiry.project_id == p.id, ClientQuoteVersion.accepted_at.is_not(None))
        )
        if finance
        else None
    )
    return dict(
        agreement=dict(seq=quote.seq, payload=quote.payload, accepted_at=quote.accepted_at)
        if quote
        else None,
        id=p.id,
        name=p.name,
        status=p.status,
        due_date=p.due_date,
        owner=owner,
        workspace_id=link.workspace_id if link else None,
        approver_id=link.approver_id if link else None,
        can_manage=bool(m and m.role in ("owner", "admin")),
        can_write=bool(owner or (m and m.role != "viewer")),
        can_approve=bool(link and link.approver_id == user_id and m and m.role != "viewer"),
        can_finance=finance,
        contract_amount=str(p.contract_amount) if finance else None,
        freelancer_name=required(db, User, p.owner_id).name,
        tasks=[
            dict(
                id=t.id,
                title=t.title,
                due_date=t.due_date,
                status=t.status,
                label=t.label,
                client_visible=t.client_visible,
            )
            for t in tasks
            if owner or t.client_visible
        ],
        deliveries=versions_out(db, p.id),
        revisions=revision_counter(db, p).model_dump(),
        extra_quotes=[
            dict(
                id=q.id,
                title=q.title,
                description=q.description,
                amount=str(q.amount),
                accepted=bool(
                    db.scalar(select(ClientExtraAcceptance.id).where(ClientExtraAcceptance.quote_id == q.id))
                ),
            )
            for q in extras
        ],
    )


def require_manager(db: Session, project_id: UUID, user_id: UUID) -> ClientProjectLink:
    p, link, m = project_access(db, project_id, user_id, write=True)
    if link is None or m is None or m.role not in ("owner", "admin"):
        raise not_found("project")
    return link


def check_approver(db: Session, link: ClientProjectLink, user_id: UUID) -> None:
    m = member(db, link.workspace_id, user_id)
    if m.role == "viewer" or link.approver_id != user_id:
        raise AppError(403, "approver_required", "최종 승인자만 처리할 수 있습니다")


def required[T](db: Session, model: type[T], identifier: UUID) -> T:
    obj = db.get(model, identifier)
    if obj is None:
        raise not_found("resource")
    return obj
