"""추출 작업: 원본 PDF → 페이지·텍스트 블록·핵심 항목 후보 → 사용자 확인 대기(needs_review)."""

import logging
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.storage import FileStorage
from app.db.models import (
    ContractField,
    ContractPage,
    ContractTextBlock,
    ContractTextVersion,
    ContractVersion,
    StoredFile,
)
from app.extraction.extractor import ExtractionCancelledError, PageResult, extract_pdf
from app.extraction.fields import TextLine, find_fields
from app.extraction.ocr import OcrEngine
from app.worker.queue import ClaimedJob, JobCancelledError, finish_job, heartbeat, lock_own_job

logger = logging.getLogger(__name__)


class PermanentJobError(Exception):
    """다시 시도해도 같은 결과인 오류 (잘못된 PDF, 읽을 수 있는 글자 없음 등)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class JobTimeoutError(PermanentJobError):
    pass


def mark_version(db: Session, version_id: object, status: str, reason: str | None = None) -> None:
    version = db.get(ContractVersion, version_id)
    if version is not None:
        version.status = status
        version.failure_reason = reason


def run_extract(
    db: Session, job: ClaimedJob, settings: Settings, storage: FileStorage, ocr: OcrEngine | None
) -> None:
    version = db.get(ContractVersion, job.contract_version_id)
    if version is None:
        raise PermanentJobError("contract_deleted", "the contract was deleted")
    stored = db.get(StoredFile, version.file_id)
    if stored is None:
        raise PermanentJobError("file_missing", "the original file is missing")
    version.status = "extracting"
    version.failure_reason = None
    db.commit()

    started = time.monotonic()

    def on_page(page_no: int, total: int, method: str | None) -> None:
        if time.monotonic() - started > settings.job_timeout_seconds:
            raise JobTimeoutError("timeout", "extraction took too long")
        try:
            heartbeat(db, job, "ocr" if method == "ocr" else "extracting", settings.job_lease_seconds)
        except JobCancelledError as exc:
            raise ExtractionCancelledError from exc
        logger.info("job %s page %d/%d %s", job.id, page_no, total, method or "")

    with storage.open(stored.object_key) as stream:
        pages = extract_pdf(
            stream,
            ocr=ocr,
            ocr_dpi=settings.ocr_dpi,
            min_chars=settings.min_text_chars_per_page,
            on_page=on_page,
        )

    if not any(page.blocks for page in pages):
        reason = "no_text" if ocr is not None else "no_text_ocr_disabled"
        raise PermanentJobError(reason, "no readable text was found in the document")

    heartbeat(db, job, "validating", settings.job_lease_seconds)
    save_extraction(db, job, version, pages)


def save_extraction(db: Session, job: ClaimedJob, version: ContractVersion, pages: list[PageResult]) -> None:
    """결과 저장과 상태 변경을 한 트랜잭션으로. run_id가 내 것이 아니면 아무것도 남기지 않는다."""
    lock_own_job(db, job)

    next_no = (
        db.execute(
            select(func.coalesce(func.max(ContractTextVersion.version_no), 0)).where(
                ContractTextVersion.contract_version_id == version.id
            )
        ).scalar_one()
        + 1
    )
    text_version = ContractTextVersion(contract_version_id=version.id, version_no=next_no, kind="extracted")
    db.add(text_version)
    db.flush()

    blocks_by_key: dict[str, ContractTextBlock] = {}
    lines: list[TextLine] = []
    for page in pages:
        db.add(
            ContractPage(
                contract_version_id=version.id,
                page_no=page.page_no,
                extraction_method=page.method,
                quality_score=round(page.quality, 3),
                needs_review=page.needs_review,
            )
        )
        for position, block in enumerate(page.blocks):
            key = f"p{page.page_no}-b{position:03d}"
            row = ContractTextBlock(
                text_version_id=text_version.id,
                page_no=page.page_no,
                block_key=key,
                position=position,
                bbox={
                    **block.bbox(),
                    "page_width": round(page.width, 1),
                    "page_height": round(page.height, 1),
                },
                text=block.text,
            )
            db.add(row)
            blocks_by_key[key] = row
            lines.append(TextLine(key=key, text=block.text))
    db.flush()

    candidates = {c.key: c for c in find_fields(lines)}
    existing = {
        f.field_key: f
        for f in db.execute(
            select(ContractField).where(ContractField.contract_version_id == version.id)
        ).scalars()
    }
    for key in ("contract_amount", "final_due_date", "payment_terms", "revision_count"):
        candidate = candidates.get(key)
        field = existing.get(key) or ContractField(contract_version_id=version.id, field_key=key)
        field.extracted_value = candidate.value if candidate else None
        field.evidence_block_id = blocks_by_key[candidate.block_key].id if candidate else None
        db.add(field)

    version.status = "needs_review"
    version.failure_reason = None
    if not finish_job(db, job, "succeeded"):
        raise RuntimeError("job ownership changed during save")
    db.commit()
