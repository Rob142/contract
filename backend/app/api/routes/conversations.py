"""Persistent requests and mutually accepted, authenticated SSE chat sessions."""

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_session_token
from app.core.errors import AppError, not_found
from app.core.security import token_digest
from app.db.models import Project, ProjectChatSession, ProjectMessage, User, UserSession
from app.db.session import get_db, get_sessionmaker
from app.schemas.client_service import ChatActionIn, MessageIn, ProjectMessageIn
from app.services.client_service import project_access, required

router = APIRouter(prefix="/client-service/projects", tags=["client-conversations"])
# Active-session expiry is a product setting; pending requests expire after one day.
CHAT_HOURS: int | None = 2


def session_state(chat: ProjectChatSession) -> str:
    if chat.state in ("pending", "active") and chat.expires_at and chat.expires_at <= datetime.now(UTC):
        return "expired"
    return chat.state


def payload(db: Session, pid: UUID, uid: UUID) -> dict[str, Any]:
    p, _, m = project_access(db, pid, uid)
    chats = list(
        db.scalars(
            select(ProjectChatSession)
            .where(ProjectChatSession.project_id == pid)
            .order_by(ProjectChatSession.created_at)
        )
    )
    active = next((c for c in reversed(chats) if session_state(c) in ("pending", "active")), None)
    is_freelancer = p.owner_id == uid
    writable = is_freelancer or bool(m and m.role != "viewer")

    def out(c: ProjectChatSession) -> dict:
        requester_freelancer = c.requested_by == p.owner_id
        return dict(
            id=c.id,
            topic=c.topic,
            state=session_state(c),
            requested_by=c.requested_by,
            requester_name=required(db, User, c.requested_by).name,
            created_at=c.created_at,
            updated_at=c.updated_at,
            expires_at=c.expires_at,
            can_respond=writable and requester_freelancer != is_freelancer,
        )

    return dict(
        current=out(active) if active else None,
        sessions=[out(c) for c in chats],
        can_write=writable,
        messages=[
            dict(
                id=x.id,
                session_id=x.session_id,
                actor_id=x.actor_id,
                actor_name=x.actor_name,
                actor_side=x.actor_side,
                body=x.body,
                created_at=x.created_at,
            )
            for x in db.scalars(
                select(ProjectMessage)
                .where(ProjectMessage.project_id == pid)
                .order_by(ProjectMessage.created_at, ProjectMessage.id)
            )
        ],
    )


def expire_open(db: Session, pid: UUID) -> ProjectChatSession | None:
    chats = list(
        db.scalars(
            select(ProjectChatSession).where(
                ProjectChatSession.project_id == pid, ProjectChatSession.state.in_(("active", "pending"))
            )
        )
    )
    for c in chats:
        if session_state(c) == "expired":
            c.state = "expired"
            c.updated_at = datetime.now(UTC)
        else:
            return c
    db.flush()
    return None


@router.get("/{pid}/conversation")
def conversation(pid: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return payload(db, pid, user.id)


@router.post("/{pid}/chat-sessions", status_code=201)
def request_chat(
    pid: UUID, body: MessageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    db.scalar(select(Project).where(Project.id == pid).with_for_update())
    _, link, _ = project_access(db, pid, user.id, write=True)
    if link is None:
        raise AppError(409, "client_not_connected", "클라이언트 워크스페이스를 먼저 연결하세요")
    if expire_open(db, pid):
        raise AppError(409, "chat_already_open", "이미 대화 요청 또는 진행 중인 채팅이 있습니다")
    c = ProjectChatSession(
        project_id=pid,
        requested_by=user.id,
        topic=body.body,
        state="pending",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db.add(c)
    db.commit()
    return payload(db, pid, user.id)


@router.post("/{pid}/chat-sessions/{cid}")
def act_chat(
    pid: UUID,
    cid: UUID,
    body: ChatActionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    db.scalar(select(Project).where(Project.id == pid).with_for_update())
    p, _, _ = project_access(db, pid, user.id, write=True)
    current = expire_open(db, pid)
    c = db.get(ProjectChatSession, cid)
    if c is None or c.project_id != pid:
        raise not_found("chat")
    if current is None or current.id != cid:
        raise AppError(409, "chat_closed", "종료되거나 만료된 대화입니다")
    opposite = (c.requested_by == p.owner_id) != (user.id == p.owner_id)
    if body.action in ("accept", "decline"):
        if not opposite or c.state != "pending":
            raise AppError(409, "chat_accept_required", "반대쪽 참여자만 대화 요청에 응답할 수 있습니다")
        c.state = "active" if body.action == "accept" else "declined"
        c.responded_by = user.id
        c.expires_at = (datetime.now(UTC) + timedelta(hours=CHAT_HOURS)) if CHAT_HOURS else None
    else:
        c.state = "closed"
    c.updated_at = datetime.now(UTC)
    db.commit()
    return payload(db, pid, user.id)


@router.post("/{pid}/messages", status_code=201)
def send_message(
    pid: UUID, body: ProjectMessageIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    db.scalar(select(Project).where(Project.id == pid).with_for_update())
    p, _, _ = project_access(db, pid, user.id, write=True)
    if body.session_id:
        chat = expire_open(db, pid)
        if chat is None or chat.id != body.session_id or chat.state != "active":
            raise AppError(
                409, "chat_accept_required", "상대방이 수락한 진행 중 채팅에서만 전송할 수 있습니다"
            )
    message = ProjectMessage(
        project_id=pid,
        session_id=body.session_id,
        actor_id=user.id,
        actor_name=user.name,
        actor_side="freelancer" if p.owner_id == user.id else "client",
        body=body.body,
    )
    db.add(message)
    db.commit()
    return payload(db, pid, user.id)


def events(pid: UUID, uid: UUID, token: str) -> Iterator[str]:
    """Close every transaction before yielding; revocation never waits for an SSE connection."""
    last = ""
    for _ in range(900):  # rotate after 15 minutes; EventSource reconnects with a fresh auth check
        try:
            with get_sessionmaker()() as db:
                valid = db.scalar(
                    select(UserSession.id).where(
                        UserSession.user_id == uid,
                        UserSession.token_hash == token_digest(token),
                        UserSession.revoked_at.is_(None),
                        UserSession.expires_at > datetime.now(UTC),
                    )
                )
                if valid is None:
                    raise not_found("session")
                data = json.dumps(jsonable_encoder(payload(db, pid, uid)), ensure_ascii=False)
        except AppError:
            yield "event: access-ended\ndata: {}\n\n"
            return
        if data != last:
            yield f"data: {data}\n\n"
            last = data
        else:
            yield ": keep-alive\n\n"
        time.sleep(1)


@router.get("/{pid}/conversation/events", response_class=StreamingResponse)
def conversation_events(
    pid: UUID,
    user: User = Depends(get_current_user),
    token: str | None = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    uid = user.id
    project_access(db, pid, uid)
    db.close()
    return StreamingResponse(
        events(pid, uid, token or ""),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
