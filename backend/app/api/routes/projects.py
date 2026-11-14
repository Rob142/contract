from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.audit import record_audit
from app.core.errors import AppError, conflict
from app.core.idempotency import require_idempotency_key, run_idempotent
from app.core.pagination import PageParams, encode_cursor, page_params
from app.core.versioning import assert_version
from app.db.models import Client, Project, Task, User
from app.db.session import get_db
from app.schemas.projects import (
    ProjectCounts,
    ProjectCreate,
    ProjectDetail,
    ProjectList,
    ProjectStatus,
    ProjectUpdate,
    TaskCreate,
    TaskOut,
)
from app.schemas.revision import RevisionDraft, RevisionDraftIn, RevisionIn
from app.services.contract_revision import apply_revision, build_draft
from app.services.projects import (
    count_by_status,
    ensure_contract_detachable,
    get_detail,
    get_owned_client,
    get_owned_project,
    list_summaries,
    list_tasks,
    next_position,
    set_status,
)
from app.services.templates import apply_template

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=ProjectList)
def list_projects(
    status: ProjectStatus | None = Query(default=None),
    page: PageParams = Depends(page_params),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectList:
    rows = list_summaries(db, user.id, status, page.limit + 1, page.offset)
    has_more = len(rows) > page.limit
    return ProjectList(
        items=rows[: page.limit],
        next_cursor=encode_cursor(page.offset + page.limit) if has_more else None,
        counts=ProjectCounts(**count_by_status(db, user.id)),
    )


@router.post("", status_code=201, response_model=ProjectDetail)
def create_project(
    body: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProjectDetail:
    if body.client_id is not None:
        client = get_owned_client(db, user.id, body.client_id)
    else:
        client = Client(owner_id=user.id, name=(body.new_client_name or "").strip())
        db.add(client)
        db.flush()

    project = Project(
        owner_id=user.id,
        client_id=client.id,
        name=body.name.strip(),
        job_type=body.job_type or user.job_type,
        start_date=body.start_date,
        due_date=body.due_date,
        contract_amount=body.contract_amount,
        included_revisions=body.included_revisions,
    )
    db.add(project)
    db.flush()
    if body.use_template:
        apply_template(db, project.id, project.job_type, project.start_date, project.due_date)
    db.commit()
    return get_detail(db, user.id, project.id)


@router.get("/{project_id}", response_model=ProjectDetail)
def read_project(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProjectDetail:
    return get_detail(db, user.id, project_id)


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProjectDetail:
    project = get_owned_project(db, user.id, project_id, lock=True)
    assert_version(project.updated_at, body.version)

    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    required = {
        "name",
        "client_id",
        "job_type",
        "contract_amount",
        "status",
    }  # included_revisions는 null 허용
    cleared = sorted(k for k, v in changes.items() if v is None and k in required)
    if cleared:
        raise AppError(422, "validation_error", "these fields cannot be empty", {"fields": cleared})
    if "client_id" in changes:
        get_owned_client(db, user.id, changes["client_id"])

    start = changes.get("start_date", project.start_date)
    due = changes.get("due_date", project.due_date)
    if start and due and due < start:
        raise AppError(
            422, "validation_error", "due_date must be on or after start_date", {"fields": ["due_date"]}
        )

    for field, value in changes.items():
        setattr(project, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    return get_detail(db, user.id, project.id)


@router.delete("/{project_id}", status_code=204, response_class=Response)
def delete_project(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    project = get_owned_project(db, user.id, project_id, lock=True)
    has_invoices = db.execute(
        text("SELECT EXISTS (SELECT 1 FROM invoices WHERE project_id = :pid)"), {"pid": project.id}
    ).scalar()
    if has_invoices:
        # 발행·입금 이력 보존 (설계서 7·9장): 보관(archived)으로 바꾸도록 안내
        raise conflict("project_has_invoices", "projects with invoices cannot be deleted; archive it instead")
    record_audit(
        db,
        actor_id=user.id,
        action="project.delete",
        target_type="project",
        target_id=project.id,
        name=project.name,
    )
    db.delete(project)
    db.commit()


@router.delete("/{project_id}/contract", response_model=ProjectDetail)
def unlink_contract(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProjectDetail:
    """프로젝트에서 계약서를 떼어 낸다. 계약서와 작업은 남는다.

    이 계약의 지급 단계로 청구한 인보이스가 하나라도 있으면(초안·취소 포함) 막는다.
    """
    project = get_owned_project(db, user.id, project_id, lock=True)
    if project.contract_version_id is None:
        raise conflict("project_has_no_contract", "this project has no linked contract")
    ensure_contract_detachable(db, project.contract_version_id)
    old_version = project.contract_version_id
    project.contract_version_id = None
    record_audit(
        db,
        actor_id=user.id,
        action="project.unlink_contract",
        target_type="project",
        target_id=project.id,
        contract_version_id=old_version,
    )
    db.commit()
    return get_detail(db, user.id, project.id)


@router.post("/{project_id}/revision-draft", response_model=RevisionDraft)
def revision_draft(
    project_id: UUID,
    body: RevisionDraftIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RevisionDraft:
    """수정 계약 반영 초안 (저장하지 않음): 청구한 옛 단계, 새 단계, 이어 붙일 제안"""
    project = get_owned_project(db, user.id, project_id)
    return build_draft(db, project, body.contract_version_id)


@router.post("/{project_id}/revise-contract", response_model=ProjectDetail)
def revise_contract(
    project_id: UUID,
    body: RevisionIn,
    idempotency_key: str = Depends(require_idempotency_key),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """청구 이력을 이어 붙여 프로젝트를 같은 계약의 새 버전으로 옮긴다."""

    def handler() -> tuple[int, Any]:
        project = get_owned_project(db, user.id, project_id, lock=True)
        apply_revision(db, user.id, project, body)
        db.flush()
        return 200, get_detail(db, user.id, project.id).model_dump(mode="json")

    status, payload = run_idempotent(
        db,
        user.id,
        idempotency_key,
        {"op": "project.revise_contract", "project_id": str(project_id), **body.model_dump(mode="json")},
        handler,
    )
    db.commit()
    return JSONResponse(payload, status_code=status)


# ---------------------------------------------------------------- 작업 (프로젝트 하위)
@router.get("/{project_id}/tasks", response_model=list[TaskOut])
def read_tasks(
    project_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TaskOut]:
    get_owned_project(db, user.id, project_id)
    return list_tasks(db, project_id)


@router.post("/{project_id}/tasks", status_code=201, response_model=TaskOut)
def create_task(
    project_id: UUID, body: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    project = get_owned_project(db, user.id, project_id, lock=True)
    task = Task(
        project_id=project.id,
        title=body.title.strip(),
        label=(body.label or "").strip() or None,
        status="todo",
        position=next_position(db, project.id, body.status),
        due_date=body.due_date,
        hours=body.hours,
        hourly_rate=body.hourly_rate,
    )
    set_status(task, body.status)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task
