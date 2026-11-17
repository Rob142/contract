from fastapi.testclient import TestClient

from tests.conftest import register
from tests.test_projects import API, add_task, make_project


def test_last_checked_item_completes_only_in_progress_task(client: TestClient) -> None:
    register(client)
    project = make_project(client)
    existing = add_task(client, project["id"], "기존 완료 작업", status="done")
    task = add_task(client, project["id"], "검수", status="doing")
    items = [
        client.post(f"{API}/tasks/{task['id']}/checklist", json={"content": name}).json()
        for name in ("규격 확인", "오탈자 확인")
    ]
    client.patch(f"{API}/checklist-items/{items[0]['id']}", json={"is_done": True})
    tasks = client.get(f"{API}/projects/{project['id']}/tasks").json()
    assert next(t for t in tasks if t["id"] == task["id"])["status"] == "doing"
    client.patch(f"{API}/checklist-items/{items[1]['id']}", json={"is_done": True})
    tasks = client.get(f"{API}/projects/{project['id']}/tasks").json()
    completed = next(t for t in tasks if t["id"] == task["id"])
    assert completed["status"] == "done"
    assert completed["completed_at"] is not None
    assert completed["position"] > next(t for t in tasks if t["id"] == existing["id"])["position"]
    assert client.get(f"{API}/projects/{project['id']}").json()["done_tasks"] == 2
    # Repeating the request must preserve completion time and position.
    client.patch(f"{API}/checklist-items/{items[1]['id']}", json={"is_done": True})
    again = client.get(f"{API}/projects/{project['id']}/tasks").json()
    assert next(t for t in again if t["id"] == task["id"])["completed_at"] == completed["completed_at"]
    # Unchecking is editable but does not silently reopen a completed task.
    client.patch(f"{API}/checklist-items/{items[0]['id']}", json={"is_done": False})
    assert (
        next(t for t in client.get(f"{API}/projects/{project['id']}/tasks").json() if t["id"] == task["id"])[
            "status"
        ]
        == "done"
    )


def test_todo_and_empty_checklists_do_not_auto_complete(client: TestClient) -> None:
    register(client)
    project = make_project(client)
    todo = add_task(client, project["id"], "아직 시작하지 않은 작업")
    empty = add_task(client, project["id"], "체크리스트 없는 작업", status="doing")
    item = client.post(f"{API}/tasks/{todo['id']}/checklist", json={"content": "확인"}).json()
    client.patch(f"{API}/checklist-items/{item['id']}", json={"is_done": True})
    tasks = client.get(f"{API}/projects/{project['id']}/tasks").json()
    assert next(t for t in tasks if t["id"] == todo["id"])["status"] == "todo"
    assert next(t for t in tasks if t["id"] == empty["id"])["status"] == "doing"
    assert client.post(
        f"{API}/projects/{project['id']}/tasks", json={"title": "완료에서 시작", "status": "done"}
    ).json()["completed_at"]
