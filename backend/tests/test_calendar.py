from fastapi.testclient import TestClient

from tests.conftest import register
from tests.test_projects import API, add_task, make_project


def test_calendar_returns_all_month_deadlines_and_filters_status_and_owner(client: TestClient) -> None:
    register(client)
    project = make_project(client)
    for index in range(7):
        add_task(client, project["id"], f"이 달 작업 {index}", due_date="2026-12-15")
    add_task(client, project["id"], "완료 작업", status="done", due_date="2026-12-15")
    add_task(client, project["id"], "지난 달", due_date="2026-11-30")
    add_task(client, project["id"], "다음 달", due_date="2027-01-01")
    add_task(client, project["id"], "날짜 미정")
    archived = make_project(client, name="보관 프로젝트")
    add_task(client, archived["id"], "보관 작업", due_date="2026-12-15")
    client.patch(f"{API}/projects/{archived['id']}", json={"status": "archived"})
    result = client.get(f"{API}/dashboard/calendar?month=2026-12")
    assert result.status_code == 200
    assert len(result.json()) == 7  # 기존 대시보드의 5개 제한을 적용하지 않는다.
    assert all(row["project_id"] == project["id"] for row in result.json())
    assert len(client.get(f"{API}/dashboard/calendar?month=2027-01").json()) == 1
    register(client, email="calendar-other@example.com")
    assert client.get(f"{API}/dashboard/calendar?month=2026-12").json() == []


def test_calendar_validates_month_and_handles_leap_day(client: TestClient) -> None:
    register(client)
    project = make_project(client)
    add_task(client, project["id"], "윤일 마감", due_date="2028-02-29")
    assert len(client.get(f"{API}/dashboard/calendar?month=2028-02").json()) == 1
    for month in ("2026-13", "2026-2", "0000-01", "9999-12"):
        assert client.get(f"{API}/dashboard/calendar", params={"month": month}).status_code == 422
    client.post(f"{API}/auth/logout")
    assert client.get(f"{API}/dashboard/calendar?month=2028-02").status_code == 401
