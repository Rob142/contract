from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.clock import today
from app.db.session import get_engine
from tests.conftest import register

API = "/api/v1"


def make_project(client: TestClient, **overrides: object) -> dict:
    body = {
        "name": "모노 스튜디오 브랜드 디자인",
        "new_client_name": "모노 스튜디오",
        "start_date": "2026-11-12",
        "due_date": "2026-11-20",
        "contract_amount": 1000000,
        **overrides,
    }
    res = client.post(f"{API}/projects", json=body)
    assert res.status_code == 201, res.text
    return res.json()


def add_task(client: TestClient, project_id: str, title: str, **extra: object) -> dict:
    res = client.post(f"{API}/projects/{project_id}/tasks", json={"title": title, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def board(client: TestClient, project_id: str) -> dict[str, list[str]]:
    tasks = client.get(f"{API}/projects/{project_id}/tasks").json()
    columns: dict[str, list[str]] = {"todo": [], "doing": [], "done": []}
    for t in tasks:
        columns[t["status"]].append(t["title"])
    return columns


def test_create_project_with_new_client_and_money_as_string(client: TestClient) -> None:
    register(client)
    project = make_project(client, contract_amount="1000000")
    assert project["client"]["name"] == "모노 스튜디오"
    assert project["contract_amount"] == "1000000"
    assert project["job_type"] == "design"  # 사용자 기본 직업군
    assert project["progress_pct"] is None  # 작업 없음 = 산정 전
    assert project["outstanding_amount"] == "0"
    assert project["payment_terms"] == []

    clients = client.get(f"{API}/clients").json()
    assert [c["name"] for c in clients] == ["모노 스튜디오"]

    # 기존 거래처로 두 번째 프로젝트
    second = make_project(client, name="2차", new_client_name=None, client_id=clients[0]["id"])
    assert second["client"]["id"] == clients[0]["id"]


def test_project_validation(client: TestClient) -> None:
    register(client)
    res = client.post(
        f"{API}/projects",
        json={"name": "x", "new_client_name": "c", "start_date": "2026-11-20", "due_date": "2026-11-12"},
    )
    assert res.status_code == 422
    res = client.post(f"{API}/projects", json={"name": "x"})  # 거래처 없음
    assert res.status_code == 422
    res = client.post(
        f"{API}/projects", json={"name": "x", "new_client_name": "c", "contract_amount": "10.5"}
    )
    assert res.status_code == 422
    res = client.post(f"{API}/projects", json={"name": "x", "new_client_name": "c", "contract_amount": -1})
    assert res.status_code == 422


def test_other_users_cannot_see_or_use_projects(client: TestClient) -> None:
    register(client, email="a@example.com")
    project = make_project(client)
    task = add_task(client, project["id"], "로고 시안")
    client_id = project["client"]["id"]

    client.cookies.clear()
    register(client, email="b@example.com")
    assert client.get(f"{API}/projects").json()["items"] == []
    assert client.get(f"{API}/projects/{project['id']}").status_code == 404
    assert client.get(f"{API}/projects/{project['id']}/tasks").status_code == 404
    assert client.patch(f"{API}/projects/{project['id']}", json={"name": "x"}).status_code == 404
    assert client.patch(f"{API}/tasks/{task['id']}", json={"title": "x"}).status_code == 404
    move = client.post(f"{API}/tasks/{task['id']}/move", json={"status": "done", "index": 0})
    assert move.status_code == 404
    assert client.delete(f"{API}/tasks/{task['id']}").status_code == 404
    # 남의 거래처로 프로젝트를 만들 수 없다
    res = client.post(f"{API}/projects", json={"name": "x", "client_id": client_id})
    assert res.status_code == 404


def test_list_counts_and_status_filter(client: TestClient) -> None:
    register(client)
    a = make_project(client, name="A", due_date="2026-11-28")
    make_project(client, name="B", due_date="2026-11-20")
    c = make_project(client, name="C")
    client.patch(f"{API}/projects/{c['id']}", json={"status": "completed"})

    res = client.get(f"{API}/projects").json()
    assert res["counts"] == {"all": 3, "active": 2, "completed": 1, "archived": 0}
    # 진행 중 먼저, 납기 빠른 순
    assert [p["name"] for p in res["items"]] == ["B", "A", "C"]

    active = client.get(f"{API}/projects", params={"status": "active"}).json()
    assert {p["name"] for p in active["items"]} == {"A", "B"}

    page = client.get(f"{API}/projects", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = client.get(f"{API}/projects", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert [p["name"] for p in rest["items"]] == ["C"] and rest["next_cursor"] is None
    assert a["id"] in {p["id"] for p in page["items"]}


def test_update_with_version_conflict(client: TestClient) -> None:
    register(client)
    project = make_project(client)
    version = project["version"]

    res = client.patch(f"{API}/projects/{project['id']}", json={"name": "변경", "version": version})
    assert res.status_code == 200
    assert res.json()["name"] == "변경"

    # 오래된 version으로 다시 수정하면 충돌
    res = client.patch(f"{API}/projects/{project['id']}", json={"name": "또 변경", "version": version})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "version_conflict"

    res = client.patch(f"{API}/projects/{project['id']}", json={"due_date": "2026-11-01"})
    assert res.status_code == 422  # 시작일보다 앞선 납기


def test_kanban_move_and_progress(client: TestClient) -> None:
    register(client)
    project = make_project(client)
    pid = project["id"]
    t1 = add_task(client, pid, "브랜드 리서치")
    t2 = add_task(client, pid, "로고 1차 시안")
    t3 = add_task(client, pid, "로고 2차 시안")
    assert board(client, pid)["todo"] == ["브랜드 리서치", "로고 1차 시안", "로고 2차 시안"]

    res = client.post(f"{API}/tasks/{t1['id']}/move", json={"status": "done", "index": 0})
    assert res.status_code == 200
    done = next(t for t in res.json() if t["id"] == t1["id"])
    assert done["completed_at"] is not None

    # 같은 열 안에서 순서 바꾸기
    client.post(f"{API}/tasks/{t3['id']}/move", json={"status": "todo", "index": 0})
    assert board(client, pid) == {
        "todo": ["로고 2차 시안", "로고 1차 시안"],
        "doing": [],
        "done": ["브랜드 리서치"],
    }

    # 범위를 넘는 index는 열 끝으로
    client.post(f"{API}/tasks/{t2['id']}/move", json={"status": "doing", "index": 99})
    assert board(client, pid)["doing"] == ["로고 1차 시안"]

    detail = client.get(f"{API}/projects/{pid}").json()
    assert (detail["total_tasks"], detail["done_tasks"], detail["progress_pct"]) == (3, 1, 33)

    # 완료에서 되돌리면 완료 시각이 지워진다
    res = client.post(f"{API}/tasks/{t1['id']}/move", json={"status": "todo", "index": 0})
    assert next(t for t in res.json() if t["id"] == t1["id"])["completed_at"] is None


def test_task_update_and_checklist(client: TestClient) -> None:
    register(client)
    project = make_project(client)
    task = add_task(client, project["id"], "최종 파일 정리", label="납품", due_date="2026-11-19")

    res = client.patch(
        f"{API}/tasks/{task['id']}", json={"label": "  ", "hours": "2.5", "hourly_rate": 50000}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["label"] is None and body["hours"] == "2.50" and body["hourly_rate"] == "50000"
    assert client.patch(f"{API}/tasks/{task['id']}", json={"title": " "}).status_code == 422

    item = client.post(f"{API}/tasks/{task['id']}/checklist", json={"content": "AI 원본 정리"}).json()
    client.post(f"{API}/tasks/{task['id']}/checklist", json={"content": "PDF 내보내기"})
    assert (
        client.patch(f"{API}/checklist-items/{item['id']}", json={"is_done": True}).json()["is_done"] is True
    )

    tasks = client.get(f"{API}/projects/{project['id']}/tasks").json()
    assert [(c["content"], c["is_done"]) for c in tasks[0]["checklist"]] == [
        ("AI 원본 정리", True),
        ("PDF 내보내기", False),
    ]

    assert client.delete(f"{API}/checklist-items/{item['id']}").status_code == 204
    assert client.delete(f"{API}/tasks/{task['id']}").status_code == 204
    assert client.get(f"{API}/projects/{project['id']}/tasks").json() == []


def test_delete_project_and_client(client: TestClient) -> None:
    register(client)
    project = make_project(client)
    add_task(client, project["id"], "작업")
    client_id = project["client"]["id"]

    res = client.delete(f"{API}/clients/{client_id}")
    assert res.status_code == 409 and res.json()["error"]["code"] == "client_in_use"

    assert client.delete(f"{API}/projects/{project['id']}").status_code == 204
    assert client.get(f"{API}/projects/{project['id']}").status_code == 404
    assert client.delete(f"{API}/clients/{client_id}").status_code == 204


def _issue_invoice(
    owner_email: str, project_id: str, no: str, total: int, paid: int, due: date, issued: date
) -> None:
    """인보이스 API가 아직 없어 SQL로 발행 상태를 만든다."""
    with get_engine().begin() as conn:
        owner = conn.execute(text("SELECT id FROM users WHERE email = :e"), {"e": owner_email}).scalar_one()
        inv = conn.execute(
            text(
                """
                INSERT INTO invoices (owner_id, project_id, title, subtotal, total)
                VALUES (:o, :p, :t, :total, :total) RETURNING id
                """
            ),
            {"o": owner, "p": project_id, "t": f"{no} 청구", "total": total},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO invoice_items (invoice_id, kind, description, unit_price, amount) "
                "VALUES (:i, 'extra', '항목', :total, :total)"
            ),
            {"i": inv, "total": total},
        )
        conn.execute(
            text(
                "UPDATE invoices SET status='issued', invoice_no=:no, issue_date=:issued, due_date=:due, "
                "snapshot='{}', issued_at=now() WHERE id=:i"
            ),
            {"no": no, "issued": issued, "due": due, "i": inv},
        )
        if paid:
            conn.execute(
                text(
                    "INSERT INTO payments (invoice_id, amount, paid_on, recorded_by) VALUES (:i, :a, :d, :o)"
                ),
                {"i": inv, "a": paid, "d": issued, "o": owner},
            )


def test_dashboard(client: TestClient) -> None:
    register(client)
    day = today()
    empty = client.get(f"{API}/dashboard").json()
    assert empty["active_projects"] == 0 and empty["outstanding_total"] == "0" and empty["projects"] == []

    project = make_project(client, start_date=None, due_date=None)
    pid = project["id"]
    add_task(client, pid, "오늘 마감", due_date=day.isoformat())
    add_task(client, pid, "다음 달 마감", due_date=(day + timedelta(days=40)).isoformat())
    add_task(client, pid, "지난 마감", due_date=(day - timedelta(days=3)).isoformat())
    done = add_task(client, pid, "완료한 작업", due_date=day.isoformat())
    client.post(f"{API}/tasks/{done['id']}/move", json={"status": "done", "index": 0})

    _issue_invoice("jiyoon@example.com", pid, "INV-1", 500000, 300000, day + timedelta(days=8), day)
    _issue_invoice(
        "jiyoon@example.com", pid, "INV-2", 200000, 0, day - timedelta(days=2), day - timedelta(days=40)
    )

    d = client.get(f"{API}/dashboard").json()
    assert d["today"] == day.isoformat()
    assert d["active_projects"] == 1
    assert d["tasks_due_today"] == 1
    assert d["tasks_due_this_week"] >= 1
    assert d["nearest_due_date"] == day.isoformat()
    assert d["tasks_completed_this_month"] == 1
    assert [u["title"] for u in d["upcoming"]] == ["오늘 마감", "다음 달 마감"]

    assert d["billed_this_month"] == "500000"  # 지난달 발행분 제외
    assert d["paid_total"] == "300000"
    assert d["outstanding_total"] == "400000"  # 200,000 + 200,000
    # 연체가 먼저
    assert [(i["invoice_no"], i["is_overdue"], i["payment_status"]) for i in d["invoices"]] == [
        ("INV-2", True, "unpaid"),
        ("INV-1", False, "partial"),
    ]
    assert d["projects"][0]["outstanding_amount"] == "400000"

    # 발행 이력이 있는 프로젝트는 삭제 대신 보관
    res = client.delete(f"{API}/projects/{pid}")
    assert res.status_code == 409 and res.json()["error"]["code"] == "project_has_invoices"


def test_dashboard_todos_link_next_actions(client: TestClient) -> None:
    """대시보드 '지금 할 일'이 확인할 계약서·발행할 초안·청구할 단계·마감 작업을 모아 해당 화면을 가리킨다."""
    from tests.test_invoices import key, project_from_contract, stage_invoice, term_ids

    register(client)
    project, _ = project_from_contract(client)
    todos = client.get(f"{API}/dashboard").json()["todos"]
    stage = next(t for t in todos if t["kind"] == "stage_to_bill")
    # 선금은 바로 청구 대상, 잔금은 작업이 남아 있어 아직 아님
    assert stage["title"] == "선금 50% 청구하기" and stage["target"] == "invoice_new"
    assert stage["target_id"] == project["id"]
    assert not any(t["title"] == "잔금 50% 청구하기" for t in todos)

    terms = term_ids(client, project["id"])
    draft = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "디자인 선금")
    todos = client.get(f"{API}/dashboard").json()["todos"]
    assert {"kind": "invoice_draft", "target_id": draft["id"]}.items() <= next(
        t for t in todos if t["kind"] == "invoice_draft"
    ).items()
    assert not any(t["kind"] == "stage_to_bill" and "선금" in t["title"] for t in todos)

    # 프로젝트 상세: 연결된 계약서와 단계별 청구 현황
    client.post(f"{API}/invoices/{draft['id']}/issue", json={}, headers=key())
    detail = client.get(f"{API}/projects/{project['id']}").json()
    assert detail["contract_id"] is not None
    statuses = {t["label"]: t["billing_status"] for t in detail["payment_terms"]}
    assert statuses == {"선금 50%": "billed", "잔금 50%": "unbilled"}

    # 작업을 모두 끝내면 잔금 청구가 할 일에 뜬다
    for task in client.get(f"{API}/projects/{project['id']}/tasks").json():
        client.post(f"{API}/tasks/{task['id']}/move", json={"status": "done", "index": 0})
    todos = client.get(f"{API}/dashboard").json()["todos"]
    assert any(t["title"] == "잔금 50% 청구하기" for t in todos)

    # 계약서 목록에서 연결된 프로젝트로 갈 수 있다
    contracts = client.get(f"{API}/contracts").json()["items"]
    assert contracts[0]["project_id"] == project["id"]
