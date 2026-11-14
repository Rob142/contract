"""첨부: 단계 결과물 링크·파일과 외부 증빙. 모든 접근은 소유권 확인 후에만 한다."""

import mimetypes
import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.audit import record_audit
from app.core.config import get_settings
from app.core.errors import AppError, not_found
from app.core.storage import FileStorage, FileTooLargeError, get_storage
from app.db.models import Attachment, StoredFile, User
from app.db.session import get_db
from app.schemas.sharing import AttachmentKind, AttachmentOut, DocType, LinkAttachmentIn
from app.services.projects import get_owned_project, get_owned_task

router = APIRouter(tags=["attachments"])

ALLOWED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".mp4", ".mov", ".mp3", ".wav",
    ".txt", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".hwp", ".hwpx", ".psd", ".ai", ".fig",
}  # fmt: skip
INLINE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp"}


def to_out(att: Attachment, stored: StoredFile | None) -> AttachmentOut:
    out = AttachmentOut.model_validate(att)
    if stored is not None:
        out = out.model_copy(
            update={"has_file": True, "file_name": stored.original_name, "file_size": stored.size_bytes}
        )
    return out


def _owned_attachment(db: Session, owner_id: UUID, attachment_id: UUID) -> Attachment:
    att = db.execute(
        select(Attachment).where(Attachment.id == attachment_id, Attachment.owner_id == owner_id)
    ).scalar_one_or_none()
    if att is None:
        raise not_found("attachment")
    return att


def _check_task(db: Session, user: User, project_id: UUID, task_id: UUID | None) -> None:
    if task_id is not None and get_owned_task(db, user.id, task_id).project_id != project_id:
        raise not_found("task")


@router.get("/projects/{project_id}/attachments", response_model=list[AttachmentOut])
def list_attachments(
    project_id: UUID,
    kind: AttachmentKind | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AttachmentOut]:
    get_owned_project(db, user.id, project_id)
    stmt = (
        select(Attachment, StoredFile)
        .outerjoin(StoredFile, StoredFile.id == Attachment.file_id)
        .where(Attachment.project_id == project_id, Attachment.owner_id == user.id)
        .order_by(Attachment.created_at.desc())
    )
    if kind:
        stmt = stmt.where(Attachment.kind == kind)
    return [to_out(a, f) for a, f in db.execute(stmt).all()]


@router.post("/projects/{project_id}/attachments/link", status_code=201, response_model=AttachmentOut)
def add_link(
    project_id: UUID,
    body: LinkAttachmentIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AttachmentOut:
    get_owned_project(db, user.id, project_id)
    _check_task(db, user, project_id, body.task_id)
    att = Attachment(
        owner_id=user.id,
        project_id=project_id,
        task_id=body.task_id,
        kind=body.kind,
        title=body.title.strip(),
        url=body.url,
    )
    db.add(att)
    db.commit()
    db.refresh(att)
    return to_out(att, None)


@router.post("/projects/{project_id}/attachments/file", status_code=201, response_model=AttachmentOut)
def add_file(
    project_id: UUID,
    file: UploadFile = File(...),
    kind: AttachmentKind = Form(default="deliverable"),
    title: str | None = Form(default=None, max_length=200),
    task_id: UUID | None = Form(default=None),
    doc_type: DocType | None = Form(default=None),
    issued_on: date | None = Form(default=None),
    amount: Decimal | None = Form(default=None, ge=0, max_digits=14, decimal_places=0),
    memo: str | None = Form(default=None, max_length=1000),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> AttachmentOut:
    get_owned_project(db, user.id, project_id)
    _check_task(db, user, project_id, task_id)
    filename = os.path.basename((file.filename or "").replace("\\", "/")).strip()[:200] or "file"
    if os.path.splitext(filename)[1].lower() not in ALLOWED_EXTENSIONS:
        raise AppError(422, "file_type_not_allowed", "this file type is not allowed")

    max_mb = get_settings().max_upload_mb
    try:
        stored = storage.put(user.id, file.file, max_mb * 1024 * 1024)
    except FileTooLargeError as exc:
        raise AppError(413, "file_too_large", f"the file exceeds {max_mb}MB") from exc

    try:
        mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        row = StoredFile(
            owner_id=user.id,
            storage_kind=stored.storage_kind,
            object_key=stored.object_key,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            mime_type=mime,
            original_name=filename,
        )
        db.add(row)
        db.flush()
        att = Attachment(
            owner_id=user.id,
            project_id=project_id,
            task_id=task_id,
            kind=kind,
            doc_type=doc_type,
            issued_on=issued_on,
            amount=amount,
            title=(title or "").strip() or filename,
            file_id=row.id,
            memo=(memo or "").strip() or None,
        )
        db.add(att)
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(stored.object_key)
        raise
    db.refresh(att)
    return to_out(att, row)


def stream_file(stored: StoredFile, storage: FileStorage, download: bool) -> StreamingResponse:
    def chunks() -> Iterator[bytes]:
        with storage.open(stored.object_key) as f:
            while chunk := f.read(64 * 1024):
                yield chunk

    # 브라우저가 실행할 수 있는 형식은 인라인으로 열지 않고 내려받게 한다
    inline = not download and stored.mime_type in INLINE_TYPES
    disposition = "inline" if inline else "attachment"
    return StreamingResponse(
        chunks(),
        media_type=stored.mime_type if inline else "application/octet-stream",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(stored.original_name)}",
            "Content-Length": str(stored.size_bytes),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/attachments/{attachment_id}/file", response_class=StreamingResponse)
def download_attachment(
    attachment_id: UUID,
    download: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> StreamingResponse:
    att = _owned_attachment(db, user.id, attachment_id)
    stored = db.get(StoredFile, att.file_id) if att.file_id else None
    if stored is None:
        raise not_found("file")
    return stream_file(stored, storage, download)


@router.delete("/attachments/{attachment_id}", status_code=204, response_class=Response)
def delete_attachment(
    attachment_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    storage: FileStorage = Depends(get_storage),
) -> None:
    att = _owned_attachment(db, user.id, attachment_id)
    if att.invoice_id is not None:
        raise AppError(409, "attachment_linked", "this document is linked to an invoice")
    stored = db.get(StoredFile, att.file_id) if att.file_id else None
    record_audit(db, actor_id=user.id, action="attachment.delete", target_type="attachment", target_id=att.id)
    db.delete(att)
    if stored is not None:
        db.flush()
        db.delete(stored)
    db.commit()
    if stored is not None:
        storage.delete(stored.object_key)
