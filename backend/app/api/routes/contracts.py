import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.audit import record_audit
from app.core.clock import now_utc, today
from app.core.config import get_settings
from app.core.errors import AppError, conflict
from app.core.idempotency import require_idempotency_key, run_idempotent
from app.core.pagination import PageParams, encode_cursor, page_params
from app.core.storage import FileStorage, FileTooLargeError, get_storage
from app.db.models import (
    AnalysisJob,
    Client,
    Contract,
    ContractField,
    ContractVersion,
    PaymentTerm,
    Project,
    StoredFile,
    Task,
    User,
)
from app.db.session import get_db
from app.extraction.fields import FIELD_KEYS, REQUIRED_FIELD_KEYS
from app.extraction.inspect import HEADER_SCAN_BYTES, PdfRejectedError, inspect_pdf, looks_like_pdf
from app.schemas.common import JobType
from app.schemas.contracts import (
    ContractCounts,
    ContractDetail,
    ContractList,
    ContractText,
    ContractUpdate,
    FieldsUpdate,
    StatusGroup,
    UploadResult,
)
from app.schemas.invoices import PaymentTermDraft, ProjectDraft, ProjectFromContract
from app.schemas.projects import ProjectDetail
from app.services.contracts import (
    STATUS_GROUPS,
    build_detail,
    build_text,
    confirmed_values,
    get_owned_contract,
    get_project_link,
    job_out,
    summary_select,
    to_summary,
)
from app.services.payment_terms import parse_payment_terms
from app.services.projects import ensure_contract_detachable, get_owned_client, get_owned_project
from app.services.projects import get_detail as get_project_detail

router = APIRouter(prefix="/contracts", tags=["contracts"])

ACTIVE_JOB_STATUSES = ("queued", "running")


def _clean_filename(name: str | None) -> str:
    base = os.path.basename((name or "").replace("\\", "/")).strip() or "contract.pdf"
    return base[:200]


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _store_version(
    db: Session,
    user: User,
    storage: FileStorage,
    file: UploadFile,
    *,
    contract: Contract | None,
    title: str | None = None,
    job_type: JobType | None = None,
    client_id: UUID | None = None,
) -> tuple[Contract, AnalysisJob]:
    """원본을 비공개 저장소에 두고 계약 버전과 추출 작업을 만든다.

    contract가 있으면 그 계약의 새 버전(수정 계약서), 없으면 새 계약(v1)이다.
    """
    settings = get_settings()
    if not looks_like_pdf(file.file.read(HEADER_SCAN_BYTES)):
        raise AppError(422, "not_pdf", "the file is not a PDF")
    file.file.seek(0)
    if client_id is not None:
        get_owned_client(db, user.id, client_id)

    try:
        stored = storage.put(user.id, file.file, settings.max_upload_mb * 1024 * 1024)
    except FileTooLargeError as exc:
        raise AppError(413, "file_too_large", f"the file exceeds {settings.max_upload_mb}MB") from exc

    try:
        with storage.open(stored.object_key) as saved:
            info = inspect_pdf(saved, settings.max_pdf_pages)

        filename = _clean_filename(file.filename)
        file_row = StoredFile(
            owner_id=user.id,
            storage_kind=stored.storage_kind,
            object_key=stored.object_key,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            mime_type="application/pdf",
            original_name=filename,
        )
        db.add(file_row)
        if contract is None:
            default_title = filename[:-4] if filename.lower().endswith(".pdf") else filename
            contract = Contract(
                owner_id=user.id,
                client_id=client_id,
                title=(title or "").strip() or default_title[:100],
                job_type=job_type or user.job_type,
            )
            db.add(contract)
            version_no = 1
        else:
            # 같은 계약에 동시에 두 버전을 올리지 않도록 계약 행을 잠근다
            db.execute(select(Contract).where(Contract.id == contract.id).with_for_update())
            version_no = (
                db.execute(
                    select(func.max(ContractVersion.version_no)).where(
                        ContractVersion.contract_id == contract.id
                    )
                ).scalar_one()
                or 0
            ) + 1
        db.flush()
        version = ContractVersion(
            contract_id=contract.id,
            owner_id=user.id,
            version_no=version_no,
            file_id=file_row.id,
            sha256=stored.sha256,
            page_count=info.page_count,
            status="uploaded",
        )
        db.add(version)
        db.flush()
        job = AnalysisJob(owner_id=user.id, contract_version_id=version.id, kind="extract")
        db.add(job)
        db.commit()
    except PdfRejectedError as exc:
        db.rollback()
        storage.delete(stored.object_key)
        raise AppError(422, exc.code, exc.message) from exc
    except Exception:
        db.rollback()
        storage.delete(stored.object_key)
        raise

    db.refresh(job)
    return contract, job


@router.post("", status_code=202, response_model=UploadResult)
def upload_contract(
    file: UploadFile = File(...),
    title: str | None = Form(default=None, max_length=100),
    job_type: JobType | None = Form(default=None),
    client_id: UUID | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> UploadResult:
    """원본을 비공개 저장소에 두고 추출 작업을 등록한다. 무거운 처리는 작업자가 한다 (202 + 작업 ID)."""
    contract, job = _store_version(
        db, user, storage, file, contract=None, title=title, job_type=job_type, client_id=client_id
    )
    return UploadResult(contract=build_detail(db, user.id, contract.id), job=job_out(job))


@router.post("/{contract_id}/versions", status_code=202, response_model=UploadResult)
def upload_contract_version(
    contract_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> UploadResult:
    """수정 계약서를 같은 계약의 새 버전으로 올린다. 추출·조건 확인은 v1과 같다."""
    contract, latest, _ = get_owned_contract(db, user.id, contract_id)
    if latest.status in ("uploaded", "extracting", "analyzing"):
        raise conflict("version_in_progress", "wait until the current version finishes processing")
    contract, job = _store_version(db, user, storage, file, contract=contract)
    return UploadResult(contract=build_detail(db, user.id, contract.id), job=job_out(job))


@router.get("", response_model=ContractList)
def list_contracts(
    group: StatusGroup | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    page: PageParams = Depends(page_params),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ContractList:
    stmt, version = summary_select(user.id)
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(Contract.title.ilike(pattern, escape="\\"), Client.name.ilike(pattern, escape="\\"))
        )

    # 탭 숫자: 검색어는 반영하고 상태 필터는 반영하지 않는다
    statuses = stmt.with_only_columns(version.status.label("status")).subquery()
    status_counts = dict(
        db.execute(select(statuses.c.status, func.count()).group_by(statuses.c.status)).tuples().all()
    )
    counts = ContractCounts(
        all=sum(status_counts.values()),
        **{
            g: sum(status_counts.get(s, 0) for s in group_statuses)
            for g, group_statuses in STATUS_GROUPS.items()
        },
    )

    if group:
        stmt = stmt.where(version.status.in_(STATUS_GROUPS[group]))
    rows = db.execute(
        stmt.order_by(version.created_at.desc(), Contract.id).limit(page.limit + 1).offset(page.offset)
    ).all()
    has_more = len(rows) > page.limit
    return ContractList(
        items=[to_summary(c, v, name, pid, pvn) for c, v, name, pid, pvn in rows[: page.limit]],
        next_cursor=encode_cursor(page.offset + page.limit) if has_more else None,
        counts=counts,
    )


@router.get("/{contract_id}", response_model=ContractDetail)
def read_contract(
    contract_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ContractDetail:
    return build_detail(db, user.id, contract_id)


@router.patch("/{contract_id}", response_model=ContractDetail)
def update_contract(
    contract_id: UUID,
    body: ContractUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ContractDetail:
    row, _, _ = get_owned_contract(db, user.id, contract_id)
    if body.title is not None:
        row.title = body.title.strip()
    if body.job_type is not None:
        row.job_type = body.job_type
    db.commit()
    return build_detail(db, user.id, contract_id)


@router.get("/{contract_id}/file", response_class=StreamingResponse)
def download_original(
    contract_id: UUID,
    download: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> StreamingResponse:
    """소유권 확인 후 원본을 스트리밍한다. 브라우저·서비스 워커가 캐시하지 않도록 no-store."""
    _, version, _ = get_owned_contract(db, user.id, contract_id)
    stored = db.get(StoredFile, version.file_id)
    if stored is None:
        raise AppError(404, "not_found", "file not found")

    def chunks() -> Iterator[bytes]:
        with storage.open(stored.object_key) as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        chunks(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(stored.original_name)}",
            "Content-Length": str(stored.size_bytes),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{contract_id}/text", response_model=ContractText)
def read_text(
    contract_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ContractText:
    _, version, _ = get_owned_contract(db, user.id, contract_id)
    return build_text(db, version.id)


@router.patch("/{contract_id}/fields", response_model=ContractDetail)
def update_fields(
    contract_id: UUID,
    body: FieldsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ContractDetail:
    """사용자 확인값 저장. 원본 추출값(extracted_value)은 그대로 두고 확인값만 따로 기록한다."""
    _, version, _ = get_owned_contract(db, user.id, contract_id)
    db.execute(select(ContractVersion).where(ContractVersion.id == version.id).with_for_update())
    if version.status not in ("needs_review", "ready", "analyzed"):
        raise conflict("contract_not_reviewable", "the contract text is not ready for review")

    fields = {
        f.field_key: f
        for f in db.execute(
            select(ContractField).where(ContractField.contract_version_id == version.id)
        ).scalars()
    }
    changes: dict[str, Any] = body.values.model_dump(exclude_unset=True)
    for key, value in changes.items():
        field = fields.get(key)
        if field is None:
            field = ContractField(contract_version_id=version.id, field_key=key)
            db.add(field)
            fields[key] = field
        text_value = value.isoformat() if hasattr(value, "isoformat") else (value.strip() if value else None)
        if field.confirmed_value != (text_value or None):
            field.confirmed_value = text_value or None
            # 확정 뒤 값을 바꾸면 다시 확인해야 한다
            field.status = "unconfirmed"
            field.confirmed_by = None
            field.confirmed_at = None

    if body.confirm:
        missing = [k for k in REQUIRED_FIELD_KEYS if not (fields.get(k) and fields[k].confirmed_value)]
        if missing:
            raise AppError(422, "missing_fields", "required fields must be confirmed", {"fields": missing})
        now = now_utc()
        for key in FIELD_KEYS:
            field = fields.get(key)
            if field is None:
                # 원문에 없는 항목(예: 수정 횟수)도 "확인함, 값 없음"으로 남긴다
                field = ContractField(contract_version_id=version.id, field_key=key)
                db.add(field)
            field.status = "confirmed"
            field.confirmed_by = user.id
            field.confirmed_at = now
        version.status = "ready"
        record_audit(
            db,
            actor_id=user.id,
            action="contract.fields_confirm",
            target_type="contract_version",
            target_id=version.id,
            keys=sorted(FIELD_KEYS),
        )
    elif changes:
        version.status = "needs_review"

    db.commit()
    return build_detail(db, user.id, contract_id)


@router.post("/{contract_id}/extract", status_code=202, response_model=UploadResult)
def retry_extract(
    contract_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UploadResult:
    """추출에 실패했거나 취소된 버전을 다시 처리한다."""
    _, version, _ = get_owned_contract(db, user.id, contract_id)
    db.execute(select(ContractVersion).where(ContractVersion.id == version.id).with_for_update())
    if version.status != "failed":
        raise conflict("contract_not_failed", "only failed extractions can be retried")
    version.status = "uploaded"
    version.failure_reason = None
    job = AnalysisJob(owner_id=user.id, contract_version_id=version.id, kind="extract")
    db.add(job)
    db.commit()
    db.refresh(job)
    return UploadResult(contract=build_detail(db, user.id, contract_id), job=job_out(job))


@router.delete("/{contract_id}", status_code=204, response_class=Response)
def delete_contract(
    contract_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> None:
    """실행 중 작업이 있거나 프로젝트에 연결된 계약은 지우지 않는다 (설계서 9장)."""
    contract, _, _ = get_owned_contract(db, user.id, contract_id)
    db.execute(select(Contract).where(Contract.id == contract.id).with_for_update())
    versions = list(
        db.execute(select(ContractVersion).where(ContractVersion.contract_id == contract.id)).scalars()
    )
    version_ids = [v.id for v in versions]

    busy = db.execute(
        select(
            exists().where(
                AnalysisJob.contract_version_id.in_(version_ids), AnalysisJob.status.in_(ACTIVE_JOB_STATUSES)
            )
        )
    ).scalar()
    if busy:
        raise conflict("contract_busy", "cancel the running job before deleting the contract")
    in_use = db.execute(select(exists().where(Project.contract_version_id.in_(version_ids)))).scalar()
    if in_use:
        raise conflict("contract_in_use", "the contract is linked to a project")

    files = list(
        db.execute(select(StoredFile).where(StoredFile.id.in_([v.file_id for v in versions]))).scalars()
    )
    record_audit(
        db,
        actor_id=user.id,
        action="contract.delete",
        target_type="contract",
        target_id=contract.id,
        versions=len(versions),
    )
    db.delete(contract)
    db.flush()
    for f in files:
        db.delete(f)
    db.commit()
    # DB에서 지운 뒤 저장소 정리 (실패해도 고아 객체만 남고 접근 경로는 없다)
    for f in files:
        storage.delete(f.object_key)


# ---------------------------------------------------------------- 계약서 → 프로젝트 (07)
def _linked_project(db: Session, contract_id: UUID) -> UUID | None:
    """이 계약(어느 버전이든)을 쓰는 프로젝트"""
    return get_project_link(db, contract_id)[0]


@router.post("/{contract_id}/project-draft", response_model=ProjectDraft)
def project_draft(
    contract_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProjectDraft:
    """확인을 마친 계약 조건으로 프로젝트 초안을 만든다 (저장하지 않음).

    작업 초안 추정은 AI 분석 단계에서 붙인다. 지금은 비워 두고 사용자가 직접 추가한다.
    """
    contract, version, _ = get_owned_contract(db, user.id, contract_id)
    if version.status not in ("ready", "analyzed"):
        raise conflict("contract_not_confirmed", "confirm the contract fields first")
    values = confirmed_values(db, version.id)
    amount = Decimal(values.get("contract_amount") or 0)
    terms = parse_payment_terms(values.get("payment_terms"), amount)
    drafts = [
        PaymentTermDraft(
            seq=t.seq,
            stage=t.stage,  # type: ignore[arg-type]
            label=t.label,
            ratio=t.ratio,
            amount=t.amount,
            requirement=t.requirement,  # type: ignore[arg-type]
        )
        for t in terms
    ] or [PaymentTermDraft(seq=1, stage="other", label="일시불 100%", ratio=Decimal(100), amount=amount)]
    due = values.get("final_due_date")
    return ProjectDraft(
        contract_id=contract.id,
        contract_title=contract.title,
        version_no=version.version_no,
        name=contract.title,
        client_id=contract.client_id,
        job_type=contract.job_type,  # type: ignore[arg-type]
        start_date=today(),
        due_date=date.fromisoformat(due) if due else None,
        contract_amount=amount,
        payment_terms_text=values.get("payment_terms"),
        payment_terms=drafts,
        tasks=[],
        linked_project_id=_linked_project(db, contract.id),
    )


@router.post("/{contract_id}/project", status_code=201, response_model=ProjectDetail)
def create_project_from_contract(
    contract_id: UUID,
    body: ProjectFromContract,
    idempotency_key: str = Depends(require_idempotency_key),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """프로젝트·지급 단계·최초 작업을 한 트랜잭션으로 만든다. 재전송 키로 중복 생성을 막는다.

    project_id가 있으면 새로 만들지 않고 계약서 없이 만든 기존 프로젝트에 연결한다.
    이때 프로젝트 정보는 확인한 값으로 갱신하고, 작업은 기존 작업 뒤에 붙인다.
    """
    contract, version, _ = get_owned_contract(db, user.id, contract_id)

    def handler() -> tuple[int, Any]:
        db.execute(select(ContractVersion).where(ContractVersion.id == version.id).with_for_update())
        if version.status not in ("ready", "analyzed"):
            raise conflict("contract_not_confirmed", "confirm the contract fields first")
        linked = _linked_project(db, contract.id)
        if linked is not None:
            if body.project_id is not None and linked == body.project_id:
                # 같은 계약의 새 버전: 청구 이력을 이어 붙이는 수정 계약 반영으로 처리한다
                raise conflict(
                    "use_contract_revision",
                    "this project already uses an earlier version; apply it as a revision",
                )
            raise conflict("contract_already_linked", "a project already uses this contract")
        terms_total = sum((t.amount for t in body.payment_terms), Decimal(0))
        if terms_total != body.contract_amount:
            raise AppError(
                422,
                "terms_total_mismatch",
                "payment terms must add up to the contract amount",
                {"terms_total": str(terms_total), "contract_amount": str(body.contract_amount)},
            )

        existing: Project | None = None
        if body.project_id is not None:
            existing = get_owned_project(db, user.id, body.project_id, lock=True)
            if existing.contract_version_id is not None:
                if not body.replace_contract:
                    raise conflict("project_has_contract", "this project is already linked to a contract")
                ensure_contract_detachable(db, existing.contract_version_id)
            if existing.status == "archived":
                raise conflict("project_archived", "restore the project before linking a contract")

        if body.client_id is not None:
            client = get_owned_client(db, user.id, body.client_id)
        elif existing is not None and body.new_client_name is None:
            client = get_owned_client(db, user.id, existing.client_id)
        else:
            client = Client(owner_id=user.id, name=(body.new_client_name or "").strip())
            db.add(client)
            db.flush()

        # 확인한 지급 단계로 교체 (아직 어떤 인보이스도 이 버전을 참조하지 않는다)
        db.execute(delete(PaymentTerm).where(PaymentTerm.contract_version_id == version.id))
        now = now_utc()
        for seq, term in enumerate(body.payment_terms, start=1):
            db.add(
                PaymentTerm(
                    contract_version_id=version.id,
                    seq=seq,
                    stage=term.stage,
                    label=term.label.strip(),
                    ratio=term.ratio,
                    amount=term.amount,
                    requirement=(term.requirement or "").strip() or None,
                    due_date=term.due_date,
                    confirmed_by=user.id,
                    confirmed_at=now,
                )
            )

        first_position = 0
        replaced_version = existing.contract_version_id if existing is not None else None
        if existing is not None:
            project = existing
            project.client_id = client.id
            project.contract_version_id = version.id
            project.name = body.name.strip()
            project.job_type = body.job_type
            project.start_date = body.start_date
            project.due_date = body.due_date
            project.contract_amount = body.contract_amount
            first_position = db.execute(
                select(func.coalesce(func.max(Task.position) + 1, 0)).where(Task.project_id == project.id)
            ).scalar_one()
        else:
            project = Project(
                owner_id=user.id,
                client_id=client.id,
                contract_version_id=version.id,
                name=body.name.strip(),
                job_type=body.job_type,
                start_date=body.start_date,
                due_date=body.due_date,
                contract_amount=body.contract_amount,
            )
            db.add(project)
        db.flush()
        for position, task in enumerate(body.tasks, start=first_position):
            db.add(
                Task(
                    project_id=project.id,
                    title=task.title.strip(),
                    label=(task.label or "").strip() or None,
                    due_date=task.due_date,
                    position=position,
                    source="manual",
                )
            )
        if contract_row := db.get(Contract, contract_id):
            contract_row.client_id = contract_row.client_id or client.id
        record_audit(
            db,
            actor_id=user.id,
            action=(
                "project.create_from_contract"
                if existing is None
                else "project.replace_contract"
                if body.replace_contract and replaced_version
                else "project.link_contract"
            ),
            target_type="project",
            target_id=project.id,
            contract_version_id=version.id,
            contract_amount=str(body.contract_amount),
        )
        db.flush()
        return (200 if existing is not None else 201), get_project_detail(db, user.id, project.id).model_dump(
            mode="json"
        )

    status, payload = run_idempotent(
        db,
        user.id,
        idempotency_key,
        {"op": "contract.project", "contract_id": str(contract_id), **body.model_dump(mode="json")},
        handler,
    )
    db.commit()
    return JSONResponse(payload, status_code=status)
