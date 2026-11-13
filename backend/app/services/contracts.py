"""계약서 조회와 응답 조립. 모든 조회는 owner_id로 범위를 제한한다."""

from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from app.core.errors import not_found
from app.db.models import (
    AnalysisJob,
    Client,
    Contract,
    ContractField,
    ContractPage,
    ContractTextBlock,
    ContractTextVersion,
    ContractVersion,
    Project,
    StoredFile,
)
from app.schemas.contracts import (
    BlockOut,
    ClientRef,
    ContractDetail,
    ContractSummary,
    ContractText,
    Evidence,
    FieldOut,
    FileInfo,
    JobOut,
    PageInfo,
    PageText,
    VersionRef,
)

FIELD_ORDER = ("contract_amount", "final_due_date", "payment_terms", "revision_count")

STATUS_GROUPS: dict[str, tuple[str, ...]] = {
    "processing": ("uploaded", "extracting", "analyzing"),
    "needs_review": ("needs_review",),
    "ready": ("ready",),
    "analyzed": ("analyzed",),
    "failed": ("failed",),
}


def _latest_version_subquery() -> Any:
    return (
        select(ContractVersion.contract_id, func.max(ContractVersion.version_no).label("version_no"))
        .group_by(ContractVersion.contract_id)
        .subquery()
    )


def summary_select(owner_id: UUID) -> tuple[Select[Any], Any]:
    """(계약 + 최신 버전 + 거래처 이름) 조회문과 최신 버전 별칭"""
    latest = _latest_version_subquery()
    cv = aliased(ContractVersion)
    linked = aliased(ContractVersion)
    # 프로젝트는 계약의 어느 버전이든 쓸 수 있다 (수정 계약 반영 전에는 옛 버전)
    project_id = (
        select(Project.id)
        .join(linked, linked.id == Project.contract_version_id)
        .where(linked.contract_id == Contract.id)
        .limit(1)
        .scalar_subquery()
        .label("project_id")
    )
    project_version_no = (
        select(linked.version_no)
        .join(Project, Project.contract_version_id == linked.id)
        .where(linked.contract_id == Contract.id)
        .limit(1)
        .scalar_subquery()
        .label("project_version_no")
    )
    stmt = (
        select(Contract, cv, Client.name.label("client_name"), project_id, project_version_no)
        .join(latest, latest.c.contract_id == Contract.id)
        .join(cv, (cv.contract_id == Contract.id) & (cv.version_no == latest.c.version_no))
        .outerjoin(Client, Client.id == Contract.client_id)
        .where(Contract.owner_id == owner_id)
    )
    return stmt, cv


def to_summary(
    contract: Contract,
    version: ContractVersion,
    client_name: str | None,
    project_id: UUID | None = None,
    project_version_no: int | None = None,
) -> ContractSummary:
    return ContractSummary(
        id=contract.id,
        title=contract.title,
        job_type=contract.job_type,  # type: ignore[arg-type]
        client=ClientRef(id=contract.client_id, name=client_name)
        if contract.client_id and client_name
        else None,
        version_id=version.id,
        version_no=version.version_no,
        status=version.status,  # type: ignore[arg-type]
        failure_reason=version.failure_reason,
        page_count=version.page_count,
        uploaded_at=version.created_at,
        project_id=project_id,
        project_version_no=project_version_no,
    )


def job_out(job: AnalysisJob) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,  # type: ignore[arg-type]
        stage=job.stage,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        error_code=job.error_code,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        cancel_requested=job.cancel_requested_at is not None,
    )


def get_owned_contract(
    db: Session, owner_id: UUID, contract_id: UUID
) -> tuple[Contract, ContractVersion, str | None]:
    stmt, _ = summary_select(owner_id)
    row = db.execute(stmt.where(Contract.id == contract_id)).one_or_none()
    if row is None:
        raise not_found("contract")
    return row[0], row[1], row[2]


def get_project_link(db: Session, contract_id: UUID) -> tuple[UUID | None, int | None]:
    """이 계약(어느 버전이든)을 쓰는 프로젝트와 그 버전 번호"""
    row = db.execute(
        select(Project.id, ContractVersion.version_no)
        .join(ContractVersion, ContractVersion.id == Project.contract_version_id)
        .where(ContractVersion.contract_id == contract_id)
        .limit(1)
    ).one_or_none()
    return (row[0], row[1]) if row else (None, None)


def confirmed_values(db: Session, version_id: UUID) -> dict[str, str | None]:
    rows = db.execute(
        select(ContractField.field_key, ContractField.confirmed_value).where(
            ContractField.contract_version_id == version_id, ContractField.status == "confirmed"
        )
    ).all()
    return {key: value for key, value in rows}


def latest_job(db: Session, version_id: UUID) -> AnalysisJob | None:
    return db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.contract_version_id == version_id)
        .order_by(AnalysisJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_text_version(db: Session, version_id: UUID) -> ContractTextVersion | None:
    return db.execute(
        select(ContractTextVersion)
        .where(ContractTextVersion.contract_version_id == version_id)
        .order_by(ContractTextVersion.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()


def build_detail(db: Session, owner_id: UUID, contract_id: UUID) -> ContractDetail:
    contract, version, client_name = get_owned_contract(db, owner_id, contract_id)
    stored = db.get(StoredFile, version.file_id)
    job = latest_job(db, version.id)

    field_rows = db.execute(
        select(ContractField, ContractTextBlock)
        .outerjoin(ContractTextBlock, ContractTextBlock.id == ContractField.evidence_block_id)
        .where(ContractField.contract_version_id == version.id)
    ).all()
    by_key = {f.field_key: (f, block) for f, block in field_rows}
    fields = [
        FieldOut(
            key=key,  # type: ignore[arg-type]
            extracted_value=f.extracted_value,
            confirmed_value=f.confirmed_value,
            status=f.status,  # type: ignore[arg-type]
            evidence=Evidence(block_key=b.block_key, page_no=b.page_no, text=b.text) if b else None,
            confirmed_at=f.confirmed_at,
        )
        for key in FIELD_ORDER
        if key in by_key
        for f, b in [by_key[key]]
    ]

    pages = db.execute(
        select(ContractPage)
        .where(ContractPage.contract_version_id == version.id)
        .order_by(ContractPage.page_no)
    ).scalars()

    project_id, project_version_no = get_project_link(db, contract.id)
    versions = list(
        db.execute(
            select(ContractVersion)
            .where(ContractVersion.contract_id == contract.id)
            .order_by(ContractVersion.version_no.desc())
        ).scalars()
    )
    previous = next((v for v in versions if v.version_no < version.version_no), None)
    return ContractDetail(
        **to_summary(contract, version, client_name, project_id, project_version_no).model_dump(),
        versions=[
            VersionRef(id=v.id, version_no=v.version_no, status=v.status, uploaded_at=v.created_at)  # type: ignore[arg-type]
            for v in versions
        ],
        previous_values=confirmed_values(db, previous.id) if previous else {},
        file=FileInfo(
            name=stored.original_name if stored else "", size_bytes=stored.size_bytes if stored else 0
        ),
        job=job_out(job) if job else None,
        fields=fields,
        pages=[
            PageInfo(
                page_no=p.page_no,
                method=p.extraction_method,  # type: ignore[arg-type]
                quality=_quality(p),
                needs_review=p.needs_review,
            )
            for p in pages
        ],
    )


def _quality(page: ContractPage | None) -> float | None:
    return float(page.quality_score) if page is not None and page.quality_score is not None else None


def build_text(db: Session, version_id: UUID) -> ContractText:
    text_version = latest_text_version(db, version_id)
    if text_version is None:
        raise not_found("extracted text")
    pages = {
        p.page_no: p
        for p in db.execute(
            select(ContractPage).where(ContractPage.contract_version_id == version_id)
        ).scalars()
    }
    blocks = db.execute(
        select(ContractTextBlock)
        .where(ContractTextBlock.text_version_id == text_version.id)
        .order_by(ContractTextBlock.page_no, ContractTextBlock.position)
    ).scalars()
    grouped: dict[int, list[BlockOut]] = {n: [] for n in pages}
    for b in blocks:
        grouped.setdefault(b.page_no, []).append(BlockOut(key=b.block_key, text=b.text, bbox=b.bbox))

    return ContractText(
        text_version_id=text_version.id,
        kind=text_version.kind,  # type: ignore[arg-type]
        pages=[
            PageText(
                page_no=n,
                method=pages[n].extraction_method if n in pages else "text",  # type: ignore[arg-type]
                quality=_quality(pages.get(n)),
                needs_review=pages[n].needs_review if n in pages else True,
                blocks=grouped[n],
            )
            for n in sorted(grouped)
        ],
    )
