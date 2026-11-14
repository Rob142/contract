"""포트폴리오: 완료한 프로젝트의 결과물·기간·직군·피드백으로 카드 초안을 만든다.

공개 응답은 허용 목록 방식이다. 금액·계약 조건은 담지 않고, 클라이언트명은 프리랜서가 켠 경우만,
피드백 인용은 공개 동의를 확인한 경우만 보인다.
"""

import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.attachments import stream_file
from app.api.routes.public import public_headers
from app.core.audit import record_audit
from app.core.clock import now_utc
from app.core.errors import AppError, conflict, not_found
from app.core.storage import FileStorage, get_storage
from app.core.versioning import assert_version
from app.db.models import (
    Attachment,
    Client,
    PortfolioAsset,
    PortfolioItem,
    PortfolioQuote,
    Project,
    StoredFile,
    Task,
    TaskFeedback,
    User,
)
from app.db.session import get_db
from app.schemas.portfolio import (
    AssetRef,
    PortfolioCreate,
    PortfolioDraft,
    PortfolioList,
    PortfolioOut,
    PortfolioUpdate,
    PublicPortfolio,
    PublicQuote,
    QuoteCandidate,
    QuoteIn,
    QuoteOut,
)
from app.services.projects import get_owned_project

router = APIRouter(tags=["portfolio"])
public_router = APIRouter(prefix="/public/portfolio", tags=["public"], dependencies=[Depends(public_headers)])

QUOTE_PREVIEW = 200


def _asset_ref(att: Attachment) -> AssetRef:
    return AssetRef(attachment_id=att.id, title=att.title, url=att.url, has_file=att.file_id is not None)


def _owned_item(db: Session, owner_id: UUID, item_id: UUID, *, lock: bool = False) -> PortfolioItem:
    stmt = select(PortfolioItem).where(PortfolioItem.id == item_id, PortfolioItem.owner_id == owner_id)
    if lock:
        stmt = stmt.with_for_update()
    item = db.execute(stmt).scalar_one_or_none()
    if item is None:
        raise not_found("portfolio item")
    return item


def _deliverables(db: Session, project_id: UUID, owner_id: UUID, ids: list[UUID]) -> list[Attachment]:
    """고른 결과물은 같은 프로젝트의 결과물이어야 한다."""
    if not ids:
        return []
    found = {
        a.id: a
        for a in db.execute(
            select(Attachment).where(
                Attachment.id.in_(ids),
                Attachment.project_id == project_id,
                Attachment.owner_id == owner_id,
                Attachment.kind == "deliverable",
            )
        ).scalars()
    }
    if len(found) != len(set(ids)):
        raise not_found("attachment")
    return [found[i] for i in dict.fromkeys(ids)]


def _check_quotes(db: Session, project_id: UUID, quotes: list[QuoteIn]) -> dict[UUID, TaskFeedback]:
    """인용은 이 프로젝트의 클라이언트 피드백만 쓴다."""
    ids = [q.feedback_id for q in quotes]
    rows = {
        f.id: f
        for f in db.execute(
            select(TaskFeedback).where(
                TaskFeedback.id.in_(ids),
                TaskFeedback.project_id == project_id,
                TaskFeedback.author_role == "client",
            )
        ).scalars()
    }
    if len(rows) != len(set(ids)):
        raise not_found("feedback")
    return rows


def _replace_assets(db: Session, item: PortfolioItem, assets: list[Attachment]) -> None:
    for row in db.execute(select(PortfolioAsset).where(PortfolioAsset.item_id == item.id)).scalars():
        db.delete(row)
    db.flush()
    for position, att in enumerate(assets):
        db.add(PortfolioAsset(item_id=item.id, attachment_id=att.id, position=position))


def _replace_quotes(db: Session, item: PortfolioItem, quotes: list[QuoteIn]) -> None:
    for row in db.execute(select(PortfolioQuote).where(PortfolioQuote.item_id == item.id)).scalars():
        db.delete(row)
    db.flush()
    for q in quotes:
        db.add(
            PortfolioQuote(
                item_id=item.id, feedback_id=q.feedback_id, quote=q.quote.strip(), anonymize=q.anonymize
            )
        )


def to_out(db: Session, item: PortfolioItem) -> PortfolioOut:
    project = db.get(Project, item.project_id)
    client = db.get(Client, project.client_id) if project else None
    assets = (
        db.execute(
            select(Attachment)
            .join(PortfolioAsset, PortfolioAsset.attachment_id == Attachment.id)
            .where(PortfolioAsset.item_id == item.id)
            .order_by(PortfolioAsset.position)
        )
        .scalars()
        .all()
    )
    quotes = db.execute(
        select(PortfolioQuote, TaskFeedback.author_name)
        .join(TaskFeedback, TaskFeedback.id == PortfolioQuote.feedback_id)
        .where(PortfolioQuote.item_id == item.id)
        .order_by(TaskFeedback.created_at)
    ).all()
    return PortfolioOut(
        id=item.id,
        project_id=item.project_id,
        title=item.title,
        description=item.description,
        job_type=item.job_type,  # type: ignore[arg-type]
        period_start=item.period_start,
        period_end=item.period_end,
        status=item.status,  # type: ignore[arg-type]
        visibility=item.visibility,  # type: ignore[arg-type]
        share_slug=item.share_slug,
        show_client_name=item.show_client_name,
        feedback_consent_at=item.feedback_consent_at,
        cover_attachment_id=item.cover_attachment_id,
        client_name=client.name if client else "",
        assets=[_asset_ref(a) for a in assets],
        quotes=[
            QuoteOut(feedback_id=q.feedback_id, quote=q.quote, anonymize=q.anonymize, author_name=name)
            for q, name in quotes
        ],
        version=item.updated_at,
    )


@router.post("/projects/{project_id}/portfolio-draft", response_model=PortfolioDraft)
def portfolio_draft(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PortfolioDraft:
    """완료한 프로젝트에서 카드 초안을 만든다. 저장하지 않는다. 완료 전이어도 막지 않고 표시만 한다."""
    project = get_owned_project(db, user.id, project_id)
    last_done = db.execute(
        select(func.max(Task.completed_at)).where(Task.project_id == project.id, Task.status == "done")
    ).scalar_one()
    end = last_done.date() if last_done else project.due_date
    deliverables = db.execute(
        select(Attachment)
        .where(Attachment.project_id == project.id, Attachment.kind == "deliverable")
        .order_by(Attachment.created_at)
    ).scalars()
    feedback = db.execute(
        select(TaskFeedback)
        .where(TaskFeedback.project_id == project.id, TaskFeedback.author_role == "client")
        .order_by(TaskFeedback.created_at)
    ).scalars()
    return PortfolioDraft(
        project_id=project.id,
        project_completed=project.status == "completed",
        title=project.name,
        description=None,
        job_type=project.job_type,  # type: ignore[arg-type]
        period_start=project.start_date,
        period_end=end if project.start_date is None or end is None or end >= project.start_date else None,
        assets=[_asset_ref(a) for a in deliverables],
        quote_candidates=[
            QuoteCandidate(feedback_id=f.id, quote=f.body[:QUOTE_PREVIEW], author_name=f.author_name)
            for f in feedback
        ],
    )


@router.get("/portfolio", response_model=PortfolioList)
def list_portfolio(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> PortfolioList:
    items = db.execute(
        select(PortfolioItem)
        .where(PortfolioItem.owner_id == user.id)
        .order_by(PortfolioItem.created_at.desc())
    ).scalars()
    return PortfolioList(items=[to_out(db, i) for i in items])


@router.post("/portfolio", status_code=201, response_model=PortfolioOut)
def create_portfolio(
    body: PortfolioCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PortfolioOut:
    project = get_owned_project(db, user.id, body.project_id, lock=True)
    if db.execute(select(PortfolioItem.id).where(PortfolioItem.project_id == project.id)).first():
        raise conflict("portfolio_exists", "this project already has a portfolio card")
    assets = _deliverables(db, project.id, user.id, body.asset_ids)
    if body.cover_attachment_id and body.cover_attachment_id not in {a.id for a in assets}:
        raise AppError(422, "validation_error", "cover must be one of the selected assets")
    _check_quotes(db, project.id, body.quotes)

    item = PortfolioItem(
        owner_id=user.id,
        project_id=project.id,
        title=body.title.strip(),
        description=(body.description or "").strip() or None,
        job_type=project.job_type,
        period_start=body.period_start,
        period_end=body.period_end,
        cover_attachment_id=body.cover_attachment_id,
    )
    db.add(item)
    db.flush()
    _replace_assets(db, item, assets)
    _replace_quotes(db, item, body.quotes)
    db.commit()
    db.refresh(item)
    return to_out(db, item)


@router.get("/portfolio/{item_id}", response_model=PortfolioOut)
def read_portfolio(
    item_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PortfolioOut:
    return to_out(db, _owned_item(db, user.id, item_id))


@router.patch("/portfolio/{item_id}", response_model=PortfolioOut)
def update_portfolio(
    item_id: UUID,
    body: PortfolioUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortfolioOut:
    item = _owned_item(db, user.id, item_id, lock=True)
    assert_version(item.updated_at, body.version)
    changes = body.model_dump(exclude_unset=True, exclude={"version"})

    for key in ("title", "description"):
        if key in changes and isinstance(changes[key], str):
            setattr(item, key, changes[key].strip() or None)
    if "title" in changes and not item.title:
        raise AppError(422, "validation_error", "title cannot be empty", {"fields": ["title"]})
    for key in ("period_start", "period_end", "show_client_name", "status"):
        if key in changes:
            if changes[key] is None and key in ("status", "show_client_name"):
                raise AppError(422, "validation_error", f"{key} cannot be empty", {"fields": [key]})
            setattr(item, key, changes[key])
    if item.period_start and item.period_end and item.period_end < item.period_start:
        raise AppError(422, "validation_error", "period_end must be on or after period_start")

    if body.asset_ids is not None:
        assets = _deliverables(db, item.project_id, user.id, body.asset_ids)
        _replace_assets(db, item, assets)
        if item.cover_attachment_id and item.cover_attachment_id not in {a.id for a in assets}:
            item.cover_attachment_id = None
    if "cover_attachment_id" in changes:
        cover = changes["cover_attachment_id"]
        if cover is not None:
            in_set = db.execute(
                select(PortfolioAsset.id).where(
                    PortfolioAsset.item_id == item.id, PortfolioAsset.attachment_id == cover
                )
            ).first()
            if in_set is None:
                raise AppError(422, "validation_error", "cover must be one of the selected assets")
        item.cover_attachment_id = cover
    if body.quotes is not None:
        _check_quotes(db, item.project_id, body.quotes)
        _replace_quotes(db, item, body.quotes)

    if body.feedback_consent is not None:
        was = item.feedback_consent_at is not None
        item.feedback_consent_at = now_utc() if body.feedback_consent else None
        if was != body.feedback_consent:
            record_audit(
                db,
                actor_id=user.id,
                action="portfolio.feedback_consent",
                target_type="portfolio",
                target_id=item.id,
                confirmed=body.feedback_consent,
            )

    if body.visibility is not None and body.visibility != item.visibility:
        if body.visibility != "private" and item.status != "ready":
            raise conflict("portfolio_not_ready", "mark the card as ready before sharing it")
        if body.visibility != "private" and item.share_slug is None:
            item.share_slug = secrets.token_urlsafe(16)
        record_audit(
            db,
            actor_id=user.id,
            action="portfolio.visibility",
            target_type="portfolio",
            target_id=item.id,
            visibility=body.visibility,
            previous=item.visibility,
        )
        item.visibility = body.visibility
    if item.status != "ready" and item.visibility != "private":
        item.visibility = "private"  # 준비 상태가 아니면 공개하지 않는다

    db.commit()
    db.refresh(item)
    return to_out(db, item)


@router.delete("/portfolio/{item_id}", status_code=204, response_class=Response)
def delete_portfolio(
    item_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    item = _owned_item(db, user.id, item_id)
    record_audit(db, actor_id=user.id, action="portfolio.delete", target_type="portfolio", target_id=item.id)
    db.delete(item)
    db.commit()


# ---------------------------------------------------------------- 공개
def _public_item(db: Session, slug: str) -> PortfolioItem:
    item = db.execute(
        select(PortfolioItem).where(PortfolioItem.share_slug == slug, PortfolioItem.visibility != "private")
    ).scalar_one_or_none()
    if item is None or item.status != "ready":
        raise not_found("portfolio")
    return item


@public_router.get("/{slug}", response_model=PublicPortfolio)
def public_portfolio(slug: str, db: Session = Depends(get_db)) -> PublicPortfolio:
    item = _public_item(db, slug)
    full = to_out(db, item)
    owner = db.get(User, item.owner_id)
    consented = item.feedback_consent_at is not None
    return PublicPortfolio(
        title=item.title,
        description=item.description,
        job_type=full.job_type,
        period_start=item.period_start,
        period_end=item.period_end,
        freelancer_name=(owner.issuer_name or owner.name) if owner else "",
        client_name=full.client_name if item.show_client_name else None,
        cover_attachment_id=item.cover_attachment_id,
        assets=full.assets,
        # 공개 동의를 확인하기 전에는 피드백 인용을 내보내지 않는다. 이름은 기본 익명
        quotes=[
            PublicQuote(quote=q.quote, author="클라이언트" if q.anonymize else q.author_name)
            for q in full.quotes
            if consented
        ],
    )


@public_router.get("/{slug}/assets/{attachment_id}/file", response_class=StreamingResponse)
def public_asset(
    slug: str, attachment_id: UUID, db: Session = Depends(get_db), storage: FileStorage = Depends(get_storage)
) -> StreamingResponse:
    item = _public_item(db, slug)
    row = db.execute(
        select(Attachment)
        .join(PortfolioAsset, PortfolioAsset.attachment_id == Attachment.id)
        .where(PortfolioAsset.item_id == item.id, Attachment.id == attachment_id)
    ).scalar_one_or_none()
    stored = db.get(StoredFile, row.file_id) if row and row.file_id else None
    if stored is None:
        raise not_found("file")
    return stream_file(stored, storage, download=False)
