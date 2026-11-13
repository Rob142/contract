from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import AppError, not_found
from app.core.versioning import assert_version
from app.db.models import Project, Task, TaskChecklistItem, User
from app.db.session import get_db
from app.schemas.projects import (
    ChecklistItemCreate,
    ChecklistItemOut,
    ChecklistItemUpdate,
    TaskMove,
    TaskOut,
    TaskUpdate,
)
from app.services.projects import get_owned_project, get_owned_task, list_tasks, move_task

router = APIRouter(tags=["tasks"])


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: UUID, body: TaskUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Task:
    task = get_owned_task(db, user.id, task_id)
    assert_version(task.updated_at, body.version)
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    for field, value in changes.items():
        if isinstance(value, str):
            value = value.strip() or None  # 빈 라벨은 비움
        if field == "title" and value is None:
            raise AppError(422, "validation_error", "title cannot be empty", {"fields": ["title"]})
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


@router.post("/tasks/{task_id}/move", response_model=list[TaskOut])
def move(
    task_id: UUID, body: TaskMove, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[TaskOut]:
    """칸반 이동. 이동 후 프로젝트의 전체 작업 목록을 돌려줘 화면을 서버 상태와 맞춘다."""
    task = get_owned_task(db, user.id, task_id)
    # 같은 프로젝트의 동시 이동을 직렬화한다
    project = get_owned_project(db, user.id, task.project_id, lock=True)
    db.refresh(task)
    move_task(db, project, task, body.status, body.index)
    db.commit()
    return list_tasks(db, project.id)


@router.delete("/tasks/{task_id}", status_code=204, response_class=Response)
def delete_task(task_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    task = get_owned_task(db, user.id, task_id)
    db.delete(task)
    db.commit()


# ---------------------------------------------------------------- 체크리스트
def _owned_item(db: Session, owner_id: UUID, item_id: UUID) -> TaskChecklistItem:
    item = db.execute(
        select(TaskChecklistItem)
        .join(Task, Task.id == TaskChecklistItem.task_id)
        .join(Project, Project.id == Task.project_id)
        .where(TaskChecklistItem.id == item_id, Project.owner_id == owner_id)
    ).scalar_one_or_none()
    if item is None:
        raise not_found("checklist item")
    return item


@router.post("/tasks/{task_id}/checklist", status_code=201, response_model=ChecklistItemOut)
def add_checklist_item(
    task_id: UUID,
    body: ChecklistItemCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskChecklistItem:
    task = get_owned_task(db, user.id, task_id)
    last = db.execute(
        select(func.max(TaskChecklistItem.position)).where(TaskChecklistItem.task_id == task.id)
    ).scalar_one()
    item = TaskChecklistItem(
        task_id=task.id, content=body.content.strip(), position=0 if last is None else last + 1
    )
    db.add(item)
    db.commit()
    return item


@router.patch("/checklist-items/{item_id}", response_model=ChecklistItemOut)
def update_checklist_item(
    item_id: UUID,
    body: ChecklistItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TaskChecklistItem:
    item = _owned_item(db, user.id, item_id)
    changes = body.model_dump(exclude_unset=True)
    if any(v is None for v in changes.values()):
        raise AppError(422, "validation_error", "fields cannot be null")
    if "content" in changes:
        item.content = changes["content"].strip()
    if "is_done" in changes:
        item.is_done = changes["is_done"]
    db.commit()
    return item


@router.delete("/checklist-items/{item_id}", status_code=204, response_class=Response)
def delete_checklist_item(
    item_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    item = _owned_item(db, user.id, item_id)
    db.delete(item)
    db.commit()
