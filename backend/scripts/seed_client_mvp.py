"""Explicit, idempotent local demo seed. Existing accounts/projects are never edited.

Run only with the user's approval: python scripts/seed_client_mvp.py <existing-email> --confirm-demo
All public names, portfolio assets and workspace/project names identify fictional data.
"""

import sys
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.core.clock import now_utc, today
from app.core.config import get_settings
from app.core.security import hash_password, new_session_token
from app.db.models import (
    Attachment,
    Client,
    ClientDelivery,
    ClientDeliveryVersion,
    ClientProjectLink,
    ClientProjectMember,
    ClientReviewEvent,
    FreelancerProfile,
    Project,
    ProjectChatSession,
    ProjectMessage,
    Task,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.session import get_sessionmaker
from app.schemas.client_service import ProfileIn


def seed(email: str) -> None:
    with get_sessionmaker()() as db:
        target = db.scalar(select(User).where(User.email == email.lower()))
        if target is None:
            raise SystemExit("Existing account not found")
        workspace_name = "[MVP 검수용] 모아숲 가상기업"
        exists = db.scalar(
            select(Workspace)
            .join(WorkspaceMember)
            .where(Workspace.name == workspace_name, WorkspaceMember.user_id == target.id)
        )
        if exists:
            print("Demo workspace already exists; no existing records modified.")
            return
        w = Workspace(name=workspace_name)
        db.add(w)
        db.flush()
        db.add(WorkspaceMember(workspace_id=w.id, user_id=target.id, role="owner"))
        origin = get_settings().allowed_origins[0].rstrip("/")
        people = [
            ("goods", "[MVP 가상] 윤서 디자이너", "굿즈 디자인 · 인쇄용 그래픽", "3300000", "goods"),
            ("brand", "[MVP 가상] 서진 디자이너", "브랜드 아이덴티티 · 로고 시스템", "1800000", "brand"),
            ("digital", "[MVP 가상] 하린 디자이너", "상세페이지 · 디지털 콘텐츠", "900000", "digital"),
        ]
        freelancers = []
        for slug, name, scope, price, asset in people:
            u = db.scalar(select(User).where(User.email == f"mvp-{slug}@example.test"))
            if u is None:
                u = User(
                    email=f"mvp-{slug}@example.test",
                    name=name,
                    password_hash=hash_password(new_session_token()),
                    job_type="design",
                    terms_agreed_at=now_utc(),
                )
                db.add(u)
                db.flush()
            profile = ProfileIn(
                published=True,
                headline=scope,
                job_type="design",
                bio="화면 검수를 위한 가상 전문가입니다. 실제 경력·고객·거래 실적이 아닙니다.",
                services=scope.split(" · "),
                scope=f"[가상 예시] {scope} · 결과물 3종",
                price=Decimal(price),
                price_type="from",
                revisions=2,
                days=20,
                available_from=today(),
                exclusions="제작·인쇄·배송비 제외",
                originals="AI·PDF 제공",
                rights="가상 예시: 계약상 사용 범위 협의",
                portfolio=[
                    dict(
                        title=f"[MVP 가상 작업] {scope}",
                        description="서비스 검수용으로 만든 가상 콘셉트입니다.",
                        contribution="가상 그래픽 콘셉트 전체",
                        url=f"{origin}/demo/{asset}.svg",
                        image_url=f"{origin}/demo/{asset}.svg",
                        assets_consent=True,
                    )
                ],
            )
            if db.get(FreelancerProfile, u.id) is None:
                db.add(
                    FreelancerProfile(
                        id=u.id,
                        published=True,
                        payload=profile.model_dump(mode="json", exclude={"published"}),
                    )
                )
            freelancers.append(u)
        f = freelancers[0]
        c = Client(owner_id=f.id, name=workspace_name)
        db.add(c)
        db.flush()
        p = Project(
            owner_id=f.id,
            client_id=c.id,
            name="[MVP 검수용] 모아숲 굿즈 디자인",
            job_type="design",
            contract_amount=Decimal("3300000"),
            included_revisions=2,
            start_date=today(),
            due_date=today() + timedelta(days=30),
        )
        db.add(p)
        db.flush()
        link = ClientProjectLink(project_id=p.id, workspace_id=w.id, approver_id=target.id)
        db.add(link)
        db.flush()
        db.add(ClientProjectMember(link_id=link.id, user_id=target.id, can_finance=True))
        for title, offset, status, label in [
            ("[검수용] 브랜드 자료 제공", -1, "todo", "고객 자료"),
            ("[검수용] 콘셉트 협의", 2, "doing", None),
            ("[검수용] 에코백·머그·스티커 납품", 20, "todo", None),
        ]:
            db.add(
                Task(
                    project_id=p.id,
                    title=title,
                    due_date=today() + timedelta(days=offset),
                    status=status,
                    client_visible=True,
                    label=label,
                )
            )
        att = Attachment(
            owner_id=f.id,
            project_id=p.id,
            kind="deliverable",
            title="[가상] 굿즈 시안",
            url=f"{origin}/demo/goods.svg",
        )
        db.add(att)
        d = ClientDelivery(project_id=p.id, title="[MVP 검수용] 굿즈 그래픽 시안")
        db.add(d)
        db.flush()
        for seq in (1, 2):
            v = ClientDeliveryVersion(
                delivery_id=d.id,
                seq=seq,
                due_date=today() + timedelta(days=3),
                payload=dict(
                    note=f"[가상 검수 데이터] {seq}차 시안입니다. 실제 계약·납품이 아닙니다.",
                    attachments=[dict(id=str(att.id), title=att.title, url=att.url, has_file=False)],
                ),
            )
            db.add(v)
            db.flush()
            if seq == 1:
                db.add(
                    ClientReviewEvent(
                        version_id=v.id,
                        actor_id=f.id,
                        actor_name=f.name,
                        workspace_name="가상 시나리오",
                        kind="comment",
                        body="[가상 예시] 이전 버전의 의견은 새 버전과 구분해서 보존됩니다.",
                    )
                )
        db.add(
            ProjectChatSession(
                project_id=p.id,
                requested_by=f.id,
                state="pending",
                topic="[MVP 가상 요청] 굿즈 인쇄 색상과 시안 확인",
                expires_at=now_utc() + timedelta(days=1),
            )
        )
        db.add(
            ProjectMessage(
                project_id=p.id,
                actor_id=f.id,
                actor_name=f.name,
                actor_side="freelancer",
                body="[MVP 가상 요청사항] 인쇄 규격과 로고 파일을 전달해 주세요.",
            )
        )
        db.commit()
        print(f"Demo workspace created: {w.id}; project: {p.id}. Existing data unchanged.")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[2] != "--confirm-demo":
        raise SystemExit("Usage: python scripts/seed_client_mvp.py <existing-email> --confirm-demo")
    seed(sys.argv[1])
