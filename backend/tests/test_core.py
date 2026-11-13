import io
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.audit import record_audit
from app.core.errors import AppError
from app.core.idempotency import run_idempotent
from app.core.pagination import PageParams, build_page, decode_cursor, encode_cursor
from app.core.storage import FileTooLargeError, LocalFileStorage
from app.core.versioning import assert_version
from app.db.models import AuditEvent, User
from app.db.session import get_sessionmaker


def _make_user(db) -> User:
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash="x",
        name="T",
        job_type="dev",
        terms_agreed_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    return user


def test_idempotency_replays_same_request_and_rejects_reuse() -> None:
    maker = get_sessionmaker()
    with maker() as db:
        user = _make_user(db)
        calls = []

        def handler() -> tuple[int, dict]:
            calls.append(1)
            return 201, {"invoice_no": "INV-2026-011", "total": "500000"}

        first = run_idempotent(db, user.id, "key-0001", {"amount": "500000"}, handler)
        db.commit()
        second = run_idempotent(db, user.id, "key-0001", {"amount": "500000"}, handler)
        db.commit()

        assert first == second == (201, {"invoice_no": "INV-2026-011", "total": "500000"})
        assert len(calls) == 1

        with pytest.raises(AppError) as exc:
            run_idempotent(db, user.id, "key-0001", {"amount": "999"}, handler)
        assert exc.value.code == "idempotency_key_reused"


def test_idempotency_failed_handler_allows_retry() -> None:
    maker = get_sessionmaker()
    with maker() as db:
        user = _make_user(db)

        def failing() -> tuple[int, dict]:
            raise AppError(409, "over_billed", "boom")

        with pytest.raises(AppError):
            run_idempotent(db, user.id, "key-0002", {"a": 1}, failing)
        db.rollback()

        assert run_idempotent(db, user.id, "key-0002", {"a": 1}, lambda: (200, {"ok": True})) == (
            200,
            {"ok": True},
        )
        db.commit()


def test_audit_record_is_saved_with_transaction() -> None:
    maker = get_sessionmaker()
    with maker() as db:
        user = _make_user(db)
        target = uuid.uuid4()
        record_audit(
            db,
            actor_id=user.id,
            action="invoice.issue",
            target_type="invoice",
            target_id=target,
            total=500000,
        )
        db.commit()
        event = db.execute(select(AuditEvent).where(AuditEvent.target_id == target)).scalar_one()
        assert event.summary == {"total": 500000}


def test_pagination_cursor_roundtrip() -> None:
    assert decode_cursor(encode_cursor(40)) == 40
    with pytest.raises(AppError):
        decode_cursor("garbage!!")

    page = build_page(list(range(21)), PageParams(limit=20, offset=0))
    assert len(page.items) == 20
    assert page.next_cursor is not None and decode_cursor(page.next_cursor) == 20
    assert build_page([1, 2], PageParams(limit=20, offset=0)).next_cursor is None


def test_version_conflict() -> None:
    now = datetime.now(UTC)
    assert_version(now, None)
    assert_version(now, now)
    with pytest.raises(AppError) as exc:
        assert_version(now, datetime(2020, 1, 1, tzinfo=UTC))
    assert exc.value.status_code == 409


def test_local_storage(tmp_path) -> None:
    storage = LocalFileStorage(str(tmp_path))
    owner = uuid.uuid4()
    stored = storage.put(owner, io.BytesIO(b"%PDF-1.4 hello"), max_bytes=1024)
    assert stored.object_key.startswith(f"{owner}/")
    assert stored.size_bytes == 14
    with storage.open(stored.object_key) as f:
        assert f.read() == b"%PDF-1.4 hello"

    with pytest.raises(FileTooLargeError):
        storage.put(owner, io.BytesIO(b"x" * 2048), max_bytes=1024)
    assert len(list((tmp_path / str(owner)).iterdir())) == 1  # 실패한 임시 파일은 남지 않음

    with pytest.raises(ValueError):
        storage.open("../../etc/passwd")

    storage.delete(stored.object_key)
    assert not (tmp_path / stored.object_key).exists()
