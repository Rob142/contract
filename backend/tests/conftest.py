"""테스트는 개발 DB 옆에 `<db>_test` 데이터베이스를 새로 만들어 마이그레이션을 적용한 뒤 실행한다."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

_dev_url = make_url(os.environ["FH_DATABASE_URL"])
TEST_DB_NAME = f"{_dev_url.database}_test"
TEST_DB_URL = _dev_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)

# 앱 설정을 읽기 전에 테스트 DB로 바꾼다
os.environ["FH_DATABASE_URL"] = TEST_DB_URL
os.environ["FH_COOKIE_SECURE"] = "false"
os.environ["FH_ALLOWED_ORIGINS"] = '["http://localhost:5173"]'
os.environ["FH_STORAGE_ROOT"] = "/tmp/fh-test-files"
os.environ["FH_OCR_ENGINE"] = "none"  # OCR 테스트에서만 켠다
os.environ["FH_LLM_COMMERCIAL_PROVIDER"] = "fake"  # 테스트는 외부 모델을 부르지 않는다

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.routes.auth import get_login_limiter  # noqa: E402
from app.db.session import get_engine  # noqa: E402
from app.main import create_app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session", autouse=True)
def test_database() -> Iterator[None]:
    admin = create_engine(
        _dev_url.set(database="postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.upgrade(cfg, "head")

    yield

    get_engine().dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    with get_engine().begin() as conn:
        conn.execute(text("TRUNCATE users, idempotency_keys, audit_events CASCADE"))
    get_login_limiter().reset()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


def register(client: TestClient, email: str = "jiyoon@example.com", password: str = "password123") -> dict:
    res = client.post(
        "/api/v1/auth/register",
        json={
            "name": "김지윤",
            "email": email,
            "password": password,
            "job_type": "design",
            "agree_terms": True,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()
