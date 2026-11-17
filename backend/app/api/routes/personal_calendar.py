"""Private account calendar: never joined to client-facing project responses."""

from datetime import date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import month_range, now_utc
from app.core.errors import AppError, not_found
from app.core.versioning import assert_version
from app.db.models import PersonalCalendarEvent, User
from app.db.session import get_db

router = APIRouter(prefix="/personal-calendar", tags=["personal-calendar"])


class EventIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=3000)
    scheduled_on: date
    is_done: bool = False


class EventUpdate(EventIn):
    version: datetime


class EventOut(EventIn):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    updated_at: datetime


def owned(db: Session, eid: UUID, uid: UUID) -> PersonalCalendarEvent:
    row = db.scalar(
        select(PersonalCalendarEvent)
        .where(
            PersonalCalendarEvent.id == eid,
            PersonalCalendarEvent.owner_id == uid,
            PersonalCalendarEvent.archived_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise not_found("personal event")
    return row


@router.get("", response_model=list[EventOut])
def list_events(
    month: str = Query(pattern=r"^[1-9][0-9]{3}-(0[1-9]|1[0-2])$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PersonalCalendarEvent]:
    try:
        start, end = month_range(date.fromisoformat(f"{month}-01"))
    except (ValueError, OverflowError) as exc:
        raise AppError(422, "validation_error", "invalid calendar month") from exc
    return list(
        db.scalars(
            select(PersonalCalendarEvent)
            .where(
                PersonalCalendarEvent.owner_id == user.id,
                PersonalCalendarEvent.archived_at.is_(None),
                PersonalCalendarEvent.scheduled_on >= start,
                PersonalCalendarEvent.scheduled_on < end,
            )
            .order_by(PersonalCalendarEvent.scheduled_on, PersonalCalendarEvent.created_at)
        )
    )


@router.post("", response_model=EventOut, status_code=201)
def create_event(
    body: EventIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PersonalCalendarEvent:
    row = PersonalCalendarEvent(owner_id=user.id, **body.model_dump())
    db.add(row)
    db.commit()
    return row


@router.put("/{eid}", response_model=EventOut)
def update_event(
    eid: UUID, body: EventUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> PersonalCalendarEvent:
    row = owned(db, eid, user.id)
    assert_version(row.updated_at, body.version)
    for key, value in body.model_dump(exclude={"version"}).items():
        setattr(row, key, value)
    row.updated_at = now_utc()
    db.commit()
    return row


@router.delete("/{eid}", status_code=204, response_class=Response)
def archive_event(eid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    row = owned(db, eid, user.id)
    row.archived_at = now_utc()
    row.updated_at = now_utc()
    db.commit()
