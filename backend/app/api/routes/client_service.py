"""Authenticated client MVP. Every resource is authorized independently of UI mode."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.attachments import stream_file
from app.core.audit import record_audit
from app.core.clock import today
from app.core.errors import AppError, not_found
from app.core.security import new_session_token, token_digest
from app.core.storage import FileStorage, get_storage
from app.db.models import (
    Attachment,
    Client,
    ClientDelivery,
    ClientDeliveryVersion,
    ClientExtraAcceptance,
    ClientInquiry,
    ClientInquiryMessage,
    ClientInvitation,
    ClientProjectLink,
    ClientProjectMember,
    ClientQuoteVersion,
    ClientReviewEvent,
    ExtraQuote,
    FreelancerProfile,
    Project,
    StoredFile,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.session import get_db
from app.schemas.client_service import (
    AcceptIn,
    DeliveryIn,
    InquiryIn,
    InviteIn,
    MemberIn,
    MessageIn,
    ProfileIn,
    ProjectMemberIn,
    PublicationIn,
    QuoteIn,
    ReviewIn,
    WorkspaceIn,
)
from app.services.client_service import (
    check_approver,
    member,
    project_access,
    project_out,
    require_manager,
    required,
    visible_projects,
)
from app.services.sharing import add_revision_request

router = APIRouter(prefix="/client-service", tags=["client-service"])
Db = Session


def fail(message: str) -> NoReturn:
    raise AppError(409, "client_conflict", message)


@router.get("/workspaces")
def workspaces(user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> list[dict[str, Any]]:
    return [
        dict(id=w.id, name=w.name, role=m.role)
        for w, m in db.execute(
            select(Workspace, WorkspaceMember)
            .join(WorkspaceMember)
            .where(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.created_at)
        )
    ]


@router.post("/workspaces", status_code=201)
def create_workspace(
    body: WorkspaceIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict[str, Any]:
    w = Workspace(name=body.name)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=user.id, role="owner"))
    db.commit()
    return dict(id=w.id, name=w.name, role="owner")


@router.get("/workspaces/{wid}/members")
def members(
    wid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> list[dict[str, Any]]:
    member(db, wid, user.id)
    return [
        dict(id=m.user_id, name=u.name, email=u.email, role=m.role)
        for m, u in db.execute(
            select(WorkspaceMember, User).join(User).where(WorkspaceMember.workspace_id == wid)
        )
    ]


@router.patch("/workspaces/{wid}/members/{uid}")
def change_member(
    wid: UUID, uid: UUID, body: MemberIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict[str, bool]:
    # Lock workspace before all membership writes, including invitation acceptance.
    db.scalar(select(Workspace).where(Workspace.id == wid).with_for_update())
    actor = member(db, wid, user.id, manage=True)
    target = member(db, wid, uid)
    if (target.role == "owner" or body.role == "owner") and actor.role != "owner":
        raise not_found("member")
    if target.role == "owner" and body.role != "owner":
        n = db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == wid, WorkspaceMember.role == "owner")
        )
        if n == 1:
            fail("먼저 다른 팀원에게 소유권을 부여하세요")
    target.role = body.role
    if body.role == "viewer":
        for link in db.scalars(
            select(ClientProjectLink).where(
                ClientProjectLink.workspace_id == wid, ClientProjectLink.approver_id == uid
            )
        ):
            link.approver_id = None
    db.commit()
    return {"ok": True}


@router.delete("/workspaces/{wid}/members/{uid}")
def remove_member(
    wid: UUID, uid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict[str, bool]:
    db.scalar(select(Workspace).where(Workspace.id == wid).with_for_update())
    actor = member(db, wid, user.id)
    target = member(db, wid, uid)
    if uid != user.id and actor.role not in ("owner", "admin"):
        raise not_found("member")
    if target.role == "owner":
        if actor.role != "owner":
            raise not_found("member")
        n = db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == wid, WorkspaceMember.role == "owner")
        )
        if n == 1:
            fail("마지막 소유자는 제거할 수 없습니다. 먼저 소유권을 이전하세요")
    links = list(db.scalars(select(ClientProjectLink).where(ClientProjectLink.workspace_id == wid)))
    for link in links:
        db.execute(
            delete(ClientProjectMember).where(
                ClientProjectMember.link_id == link.id, ClientProjectMember.user_id == uid
            )
        )
        if link.approver_id == uid:
            link.approver_id = None
    db.delete(target)
    db.commit()
    return {"ok": True}


def invite_out(i: ClientInvitation) -> dict[str, Any]:
    return dict(
        id=i.id,
        email=i.email,
        role=i.role,
        expires_at=i.expires_at,
        used_at=i.used_at,
        revoked_at=i.revoked_at,
        mail_status=i.mail_status,
    )


def make_invite(
    db: Db, user: User, body: InviteIn, wid: UUID | None = None, pid: UUID | None = None
) -> dict[str, Any]:
    if body.send_email:
        raise AppError(409, "mail_not_connected", "이메일 발송은 화면 검수 후 연결합니다")
    token = new_session_token()
    i = ClientInvitation(
        creator_id=user.id,
        workspace_id=wid,
        project_id=pid,
        email=body.email.lower(),
        role=body.role,
        token_hash=token_digest(token),
        expires_at=datetime.now(UTC) + timedelta(days=3),
    )
    db.add(i)
    db.commit()
    return dict(**invite_out(i), token=token)


@router.post("/workspaces/{wid}/invitations", status_code=201)
def team_invite(
    wid: UUID, body: InviteIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict[str, Any]:
    member(db, wid, user.id, manage=True)
    return make_invite(db, user, body, wid=wid)


@router.get("/workspaces/{wid}/invitations")
def invitations(wid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> list[dict]:
    member(db, wid, user.id, manage=True)
    return [
        invite_out(i)
        for i in db.scalars(
            select(ClientInvitation)
            .where(ClientInvitation.workspace_id == wid)
            .order_by(ClientInvitation.created_at.desc())
        )
    ]


@router.post("/projects/{pid}/connection-invitations", status_code=201)
def project_invite(
    pid: UUID, body: InviteIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict[str, Any]:
    p = db.get(Project, pid)
    if p is None or p.owner_id != user.id:
        raise not_found("project")
    if db.scalar(select(ClientProjectLink.id).where(ClientProjectLink.project_id == pid)):
        fail("이미 기업과 연결된 프로젝트입니다")
    return make_invite(db, user, body, pid=pid)


@router.delete("/invitations/{iid}")
def revoke_invite(iid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    i = db.scalar(select(ClientInvitation).where(ClientInvitation.id == iid).with_for_update())
    if i is None:
        raise not_found("invitation")
    if i.workspace_id:
        member(db, i.workspace_id, user.id, manage=True)
    elif i.creator_id != user.id:
        raise not_found("invitation")
    i.revoked_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}


@router.post("/invitations/accept")
def accept_invite(body: AcceptIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    i = db.scalar(
        select(ClientInvitation)
        .where(ClientInvitation.token_hash == token_digest(body.token))
        .with_for_update()
    )
    if (
        i is None
        or i.used_at
        or i.revoked_at
        or i.expires_at <= datetime.now(UTC)
        or i.email.casefold() != user.email.casefold()
    ):
        raise not_found("invitation")
    wid = i.workspace_id or body.workspace_id
    if wid is None:
        fail("연결할 워크스페이스를 선택하세요")
    db.scalar(select(Workspace).where(Workspace.id == wid).with_for_update())
    if i.workspace_id:
        existing = db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == wid, WorkspaceMember.user_id == user.id
            )
        )
        if existing is None:
            db.add(WorkspaceMember(workspace_id=wid, user_id=user.id, role=i.role))
    else:
        member(db, wid, user.id, manage=True)
        p = db.scalar(select(Project).where(Project.id == i.project_id).with_for_update())
        if p is None:
            raise not_found("project")
        if p.owner_id == user.id:
            fail("자신의 프로젝트를 클라이언트로 수락할 수 없습니다")
        if db.scalar(select(ClientProjectLink.id).where(ClientProjectLink.project_id == p.id)):
            fail("이미 연결된 프로젝트입니다")
        link = ClientProjectLink(project_id=p.id, workspace_id=wid, approver_id=user.id)
        db.add(link)
        db.flush()
        db.add(ClientProjectMember(link_id=link.id, user_id=user.id, can_finance=True))
    i.used_at = datetime.now(UTC)
    db.commit()
    return dict(workspace_id=wid, project_id=i.project_id)


@router.get("/workspaces/{wid}/projects")
def workspace_projects(
    wid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> list[dict]:
    return [project_out(db, p.id, user.id) for p in visible_projects(db, wid, user.id)]


@router.get("/projects/{pid}")
def read_project(pid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    return project_out(db, pid, user.id)


@router.get("/projects/{pid}/members")
def project_members(
    pid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> list[dict]:
    _, link, _ = project_access(db, pid, user.id)
    if link is None:
        return []
    return [
        dict(id=g.user_id, name=u.name, can_finance=g.can_finance, approver=g.user_id == link.approver_id)
        for g, u in db.execute(
            select(ClientProjectMember, User).join(User).where(ClientProjectMember.link_id == link.id)
        )
    ]


@router.post("/projects/{pid}/members")
def grant_project(
    pid: UUID, body: ProjectMemberIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    # same lock as reviews: an approver cannot be changed concurrently with a decision
    db.scalar(select(Project).where(Project.id == pid).with_for_update())
    link = require_manager(db, pid, user.id)
    target = member(db, link.workspace_id, body.user_id)
    if body.approver and target.role == "viewer":
        fail("열람자는 승인자가 될 수 없습니다")
    grant = db.scalar(
        select(ClientProjectMember).where(
            ClientProjectMember.link_id == link.id, ClientProjectMember.user_id == body.user_id
        )
    )
    if grant is None:
        grant = ClientProjectMember(link_id=link.id, user_id=body.user_id, can_finance=body.can_finance)
        db.add(grant)
    else:
        grant.can_finance = body.can_finance
    if body.approver:
        link.approver_id = body.user_id
    elif link.approver_id == body.user_id:
        link.approver_id = None
    db.commit()
    return {"ok": True}


@router.delete("/projects/{pid}/members/{uid}")
def revoke_project(
    pid: UUID, uid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    db.scalar(select(Project).where(Project.id == pid).with_for_update())
    link = require_manager(db, pid, user.id)
    db.execute(
        delete(ClientProjectMember).where(
            ClientProjectMember.link_id == link.id, ClientProjectMember.user_id == uid
        )
    )
    if link.approver_id == uid:
        link.approver_id = None
    db.commit()
    return {"ok": True}


@router.put("/projects/{pid}/published-tasks")
def publish_tasks(
    pid: UUID, body: PublicationIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    p = db.get(Project, pid)
    if p is None or p.owner_id != user.id:
        raise not_found("project")
    tasks = list(db.scalars(select(Task).where(Task.project_id == pid)))
    if set(body.task_ids) - {t.id for t in tasks}:
        raise not_found("task")
    for t in tasks:
        t.client_visible = t.id in body.task_ids
    db.commit()
    return {"ok": True}


@router.post("/projects/{pid}/deliveries", status_code=201)
def submit_delivery(
    pid: UUID, body: DeliveryIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    p = db.scalar(select(Project).where(Project.id == pid).with_for_update())
    if p is None or p.owner_id != user.id:
        raise not_found("project")
    snapshots = []
    for aid in dict.fromkeys(body.attachment_ids):
        a = db.get(Attachment, aid)
        if a is None or a.owner_id != user.id or a.project_id != pid or a.kind != "deliverable":
            raise not_found("attachment")
        snapshots.append(dict(id=str(a.id), title=a.title, url=a.url, has_file=bool(a.file_id)))
    d = db.get(ClientDelivery, body.delivery_id) if body.delivery_id else None
    if body.delivery_id and (d is None or d.project_id != pid):
        raise not_found("delivery")
    if d is None:
        d = ClientDelivery(project_id=pid, title=body.title)
        db.add(d)
        db.flush()
    count = (
        db.scalar(
            select(func.count())
            .select_from(ClientDeliveryVersion)
            .where(ClientDeliveryVersion.delivery_id == d.id)
        )
        or 0
    )
    v = ClientDeliveryVersion(
        delivery_id=d.id,
        seq=count + 1,
        payload=dict(note=body.note, attachments=snapshots),
        due_date=body.due_date,
    )
    db.add(v)
    db.commit()
    return {"id": v.id, "delivery_id": d.id, "seq": v.seq}


@router.post("/versions/{vid}/reviews")
def review(
    vid: UUID, body: ReviewIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    v = db.get(ClientDeliveryVersion, vid)
    d = db.get(ClientDelivery, v.delivery_id) if v else None
    if d is None or v is None:
        raise not_found("version")
    db.scalar(select(Project).where(Project.id == d.project_id).with_for_update())
    p, link, m = project_access(db, d.project_id, user.id, write=True)
    decision = body.kind in ("approved", "changes")
    if decision:
        if link is None or p.owner_id == user.id:
            raise AppError(403, "approver_required", "클라이언트 최종 승인자가 처리해야 합니다")
        check_approver(db, link, user.id)
        latest = db.scalar(
            select(func.max(ClientDeliveryVersion.seq)).where(ClientDeliveryVersion.delivery_id == d.id)
        )
        if v.seq != latest:
            fail("최신 버전에서 검수를 진행하세요")
        previous = db.scalar(
            select(ClientReviewEvent).where(
                ClientReviewEvent.version_id == vid, ClientReviewEvent.kind.in_(("approved", "changes"))
            )
        )
        if previous:
            if previous.kind == body.kind and previous.actor_id == user.id and previous.body == body.body:
                return {"ok": True, "id": previous.id}
            fail("이 버전은 이미 검수가 종료되었습니다")
    rev = add_revision_request(db, p.id, body.body, user.name, None) if body.kind == "changes" else None
    event = ClientReviewEvent(
        version_id=vid,
        actor_id=user.id,
        actor_name=user.name,
        workspace_name=required(db, Workspace, link.workspace_id).name if link and m else "프리랜서",
        kind=body.kind,
        body=body.body,
        revision_request_id=rev.id if rev else None,
    )
    db.add(event)
    record_audit(
        db,
        actor_id=user.id,
        action=f"client.review.{body.kind}",
        target_type="delivery_version",
        target_id=vid,
    )
    db.commit()
    return {"ok": True, "id": event.id}


@router.get("/projects/{pid}/attachments/{aid}/file", response_class=StreamingResponse)
def client_file(
    pid: UUID,
    aid: UUID,
    user: User = Depends(get_current_user),
    db: Db = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> StreamingResponse:
    p, _, _ = project_access(db, pid, user.id)
    a = db.get(Attachment, aid)
    if a is None or a.project_id != pid:
        raise not_found("file")
    if p.owner_id != user.id:
        published = any(
            str(aid) == x["id"]
            for v in db.scalars(
                select(ClientDeliveryVersion).join(ClientDelivery).where(ClientDelivery.project_id == pid)
            )
            for x in v.payload["attachments"]
        )
        if not published:
            raise not_found("file")
    f = db.get(StoredFile, a.file_id) if a.file_id else None
    if f is None:
        raise not_found("file")
    return stream_file(f, storage, True)


@router.post("/extra-quotes/{qid}/accept")
def accept_extra(qid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    q = db.get(ExtraQuote, qid)
    if q is None:
        raise not_found("quote")
    db.scalar(select(Project).where(Project.id == q.project_id).with_for_update())
    _, link, _ = project_access(db, q.project_id, user.id, write=True, finance=True)
    if link is None:
        raise not_found("quote")
    check_approver(db, link, user.id)
    if not db.scalar(select(ClientExtraAcceptance.id).where(ClientExtraAcceptance.quote_id == qid)):
        db.add(
            ClientExtraAcceptance(
                quote_id=qid,
                actor_id=user.id,
                payload=dict(title=q.title, description=q.description, amount=str(q.amount)),
            )
        )
    db.commit()
    return {"ok": True}


@router.get("/profile")
def my_profile(user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    p = db.get(FreelancerProfile, user.id)
    return dict(id=user.id, name=user.name, published=p.published, **p.payload) if p else {}


@router.put("/profile")
def save_profile(body: ProfileIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    p = db.get(FreelancerProfile, user.id)
    if p is None:
        p = FreelancerProfile(id=user.id)
        db.add(p)
    p.published = body.published
    p.payload = body.model_dump(mode="json", exclude={"published"})
    p.updated_at = datetime.now(UTC)
    db.commit()
    return dict(id=user.id, name=user.name, published=p.published, **p.payload)


@router.get("/experts")
def experts(
    q: str = Query(default="", max_length=150),
    job: str = Query(default="", max_length=30),
    budget: Decimal | None = Query(default=None, ge=0, max_digits=14, decimal_places=0),
    due: date | None = None,
    user: User = Depends(get_current_user),
    db: Db = Depends(get_db),
) -> list[dict]:
    rows = db.execute(select(FreelancerProfile, User).join(User).where(FreelancerProfile.published.is_(True)))
    out = []
    for p, u in rows:
        data = p.payload
        if job and data["job_type"] != job:
            continue
        search = " ".join([u.name, data["headline"], data["bio"], *data["services"]]).casefold()
        if q and q.casefold() not in search:
            continue
        price = data.get("price")
        if budget is not None and price is not None and Decimal(price) > budget:
            continue
        available = data.get("available_from")
        if due and available and date.fromisoformat(available) > due:
            continue
        reasons = []
        if job:
            reasons.append("선택한 업무 분야 일치")
        if q:
            reasons.append("프로필에 검색어 포함")
        if budget is not None:
            reasons.append(
                "제시 시작 가격이 예산 이하 · 최종 견적 확인 필요" if price is not None else "가격 협의 필요"
            )
        if due:
            days = data.get("days")
            if available and days:
                start = max(today(), date.fromisoformat(available))
                reasons.append(
                    "등록된 기간 기준 납기 내 작업 가능"
                    if start + timedelta(days=days) <= due
                    else "희망 납기 협의 필요"
                )
            else:
                reasons.append("작업 일정 확인 필요")
        out.append(dict(id=u.id, name=u.name, **data, reasons=reasons))
    return sorted(out, key=lambda x: str(x["name"]))


@router.get("/experts/{uid}")
def expert(uid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    p = db.get(FreelancerProfile, uid)
    if p is None or not p.published:
        raise not_found("profile")
    return dict(id=p.id, name=required(db, User, uid).name, **p.payload)


def inquiry_access(db: Db, iid: UUID, user: User, write: bool = False) -> ClientInquiry:
    i = db.get(ClientInquiry, iid)
    if i is None:
        raise not_found("inquiry")
    if i.freelancer_id == user.id:
        if i.status == "draft":
            raise not_found("inquiry")
        return i
    m = member(db, i.workspace_id, user.id)
    # Inquiries are private to their creator until the resulting project is granted.
    if i.creator_id != user.id:
        raise not_found("inquiry")
    if write and m.role == "viewer":
        raise not_found("inquiry")
    return i


def inquiry_out(db: Db, i: ClientInquiry) -> dict:
    return dict(
        id=i.id,
        workspace_id=i.workspace_id,
        freelancer_id=i.freelancer_id,
        freelancer_name=required(db, User, i.freelancer_id).name,
        creator_id=i.creator_id,
        client_name=required(db, Workspace, i.workspace_id).name,
        payload=i.payload,
        status=i.status,
        project_id=i.project_id,
        quotes=[
            dict(id=q.id, seq=q.seq, payload=q.payload, accepted_at=q.accepted_at, accepted_by=q.accepted_by)
            for q in db.scalars(
                select(ClientQuoteVersion)
                .where(ClientQuoteVersion.inquiry_id == i.id)
                .order_by(ClientQuoteVersion.seq)
            )
        ],
        messages=[
            dict(id=m.id, actor_name=m.actor_name, body=m.body, created_at=m.created_at)
            for m in db.scalars(
                select(ClientInquiryMessage)
                .where(ClientInquiryMessage.inquiry_id == i.id)
                .order_by(ClientInquiryMessage.created_at)
            )
        ],
    )


@router.get("/inquiries")
def inquiries(
    wid: UUID | None = None, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> list[dict]:
    if wid:
        member(db, wid, user.id)
        stmt = select(ClientInquiry).where(
            ClientInquiry.workspace_id == wid, ClientInquiry.creator_id == user.id
        )
    else:
        stmt = select(ClientInquiry).where(
            ClientInquiry.freelancer_id == user.id, ClientInquiry.status != "draft"
        )
    return [inquiry_out(db, i) for i in db.scalars(stmt.order_by(ClientInquiry.created_at.desc()))]


@router.post("/workspaces/{wid}/inquiries", status_code=201)
def create_inquiry(
    wid: UUID, body: InquiryIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    m = member(db, wid, user.id)
    if m.role == "viewer":
        raise not_found("workspace")
    profile = db.get(FreelancerProfile, body.freelancer_id)
    if profile is None or not profile.published:
        raise not_found("profile")
    if body.freelancer_id == user.id:
        fail("자신에게 의뢰할 수 없습니다")
    i = ClientInquiry(
        workspace_id=wid,
        creator_id=user.id,
        freelancer_id=body.freelancer_id,
        payload=body.model_dump(mode="json", exclude={"freelancer_id", "send"}),
        status="sent" if body.send else "draft",
    )
    db.add(i)
    db.commit()
    return inquiry_out(db, i)


@router.post("/inquiries/{iid}/send")
def send_inquiry(iid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    i = inquiry_access(db, iid, user, write=True)
    if i.creator_id != user.id:
        raise not_found("inquiry")
    if i.status == "draft":
        i.status = "sent"
    db.commit()
    return inquiry_out(db, i)


@router.post("/inquiries/{iid}/messages")
def inquiry_message(
    iid: UUID, body: MessageIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    i = inquiry_access(db, iid, user, write=True)
    db.add(ClientInquiryMessage(inquiry_id=i.id, actor_id=user.id, actor_name=user.name, body=body.body))
    if i.status == "sent":
        i.status = "negotiating"
    db.commit()
    return inquiry_out(db, i)


@router.post("/inquiries/{iid}/quotes", status_code=201)
def propose_quote(
    iid: UUID, body: QuoteIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    db.scalar(select(ClientInquiry).where(ClientInquiry.id == iid).with_for_update())
    i = inquiry_access(db, iid, user, write=True)
    if i.freelancer_id != user.id:
        raise not_found("inquiry")
    if i.status == "contracted":
        fail("확정된 계약은 변경할 수 없습니다")
    if body.client_due_date > body.due_date:
        fail("자료 제공일은 납품일 이전이어야 합니다")
    seq = (
        db.scalar(
            select(func.count()).select_from(ClientQuoteVersion).where(ClientQuoteVersion.inquiry_id == iid)
        )
        or 0
    )
    db.add(ClientQuoteVersion(inquiry_id=iid, seq=seq + 1, payload=body.model_dump(mode="json")))
    i.status = "quoted"
    db.commit()
    return inquiry_out(db, i)


@router.post("/quotes/{qid}/accept")
def accept_quote(qid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)) -> dict:
    q = db.get(ClientQuoteVersion, qid)
    if q is None:
        raise not_found("quote")
    db.scalar(select(ClientInquiry).where(ClientInquiry.id == q.inquiry_id).with_for_update())
    i = inquiry_access(db, q.inquiry_id, user, write=True)
    if i.creator_id != user.id or i.freelancer_id == user.id:
        raise not_found("quote")
    if i.status == "contracted":
        if q.accepted_at:
            return inquiry_out(db, i)
        fail("이미 다른 견적 버전으로 확정되었습니다")
    latest = db.scalar(select(func.max(ClientQuoteVersion.seq)).where(ClientQuoteVersion.inquiry_id == i.id))
    if q.seq != latest:
        fail("최신 견적을 확인하세요")
    m = member(db, i.workspace_id, user.id)
    if m.role not in ("owner", "admin"):
        fail("견적 확정은 의뢰를 작성한 소유자 또는 관리자만 할 수 있습니다")
    w = required(db, Workspace, i.workspace_id)
    c = Client(owner_id=i.freelancer_id, name=w.name)
    db.add(c)
    db.flush()
    # Preserve the accepted quote as the immutable scope; no electronic-signature claim.
    p = Project(
        owner_id=i.freelancer_id,
        client_id=c.id,
        name=i.payload["title"],
        job_type=required(db, User, i.freelancer_id).job_type,
        due_date=date.fromisoformat(q.payload["due_date"]),
        contract_amount=Decimal(q.payload["amount"]),
        included_revisions=q.payload["revisions"],
    )
    db.add(p)
    db.flush()
    db.add(
        Task(
            project_id=p.id,
            title="클라이언트 자료 제공",
            label="고객 자료",
            due_date=date.fromisoformat(q.payload["client_due_date"]),
            client_visible=True,
        )
    )
    db.add(
        Task(
            project_id=p.id,
            title="계약 결과물 납품",
            due_date=date.fromisoformat(q.payload["due_date"]),
            client_visible=True,
        )
    )
    link = ClientProjectLink(project_id=p.id, workspace_id=w.id, approver_id=user.id)
    db.add(link)
    db.flush()
    db.add(ClientProjectMember(link_id=link.id, user_id=user.id, can_finance=True))
    q.accepted_at = datetime.now(UTC)
    q.accepted_by = user.id
    i.project_id = p.id
    i.status = "contracted"
    db.commit()
    return inquiry_out(db, i)


@router.get("/projects/{pid}/owner-attachments")
def owner_attachments(
    pid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> list[dict]:
    p = db.get(Project, pid)
    if p is None or p.owner_id != user.id:
        raise not_found("project")
    return [
        dict(id=a.id, title=a.title, kind=a.kind)
        for a in db.scalars(
            select(Attachment).where(Attachment.project_id == pid, Attachment.owner_id == user.id)
        )
    ]


@router.post("/projects/{pid}/tasks/{tid}/complete")
def complete_client_task(
    pid: UUID, tid: UUID, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    project_access(db, pid, user.id, write=True)
    t = db.scalar(select(Task).where(Task.id == tid, Task.project_id == pid).with_for_update())
    if t is None or (not t.client_visible and t.due_date is None) or t.label != "고객 자료":
        raise not_found("task")
    t.status = "done"
    t.completed_at = datetime.now(UTC)
    db.commit()
    return {"ok": True}


@router.put("/inquiries/{iid}")
def edit_draft(
    iid: UUID, body: InquiryIn, user: User = Depends(get_current_user), db: Db = Depends(get_db)
) -> dict:
    db.scalar(select(ClientInquiry).where(ClientInquiry.id == iid).with_for_update())
    i = inquiry_access(db, iid, user, write=True)
    if i.creator_id != user.id or i.status != "draft":
        fail("전송 전 의뢰만 수정할 수 있습니다. 전송 후 변경은 협의 메시지로 남겨 주세요")
    if i.freelancer_id != body.freelancer_id:
        fail("다른 전문가에게는 새 의뢰를 작성하세요")
    i.payload = body.model_dump(mode="json", exclude={"freelancer_id", "send"})
    if body.send:
        i.status = "sent"
    db.commit()
    return inquiry_out(db, i)
