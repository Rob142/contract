"""Personal schedules and client-visible project dates have distinct authorization."""

from tests.test_client_service import P, actor, connected

CAL = "/api/v1/personal-calendar"


def test_personal_calendar_crud_ownership_month_and_optimistic_lock(client):
    owner, _ = actor(client, "calendar-owner@example.com", "freelancer")
    other, _ = actor(client, "calendar-other@example.com")
    body = dict(title="Private preparation", notes="Never disclose this memo", scheduled_on="2026-11-30")
    res = owner.post(CAL, json=body)
    assert res.status_code == 201, res.text
    entry = res.json()
    assert owner.get(CAL + "?month=2026-11").json()[0]["notes"] == body["notes"]
    assert owner.get(CAL + "?month=2026-12").json() == []
    assert other.get(CAL + "?month=2026-11").json() == []
    url = CAL + "/" + entry["id"]
    update = dict(**body, is_done=True, version=entry["updated_at"])
    assert other.put(url, json=update).status_code == 404
    assert other.delete(url).status_code == 404
    saved = owner.put(url, json=update)
    assert saved.status_code == 200 and saved.json()["is_done"] is True
    assert owner.put(url, json=update).status_code == 409
    assert owner.delete(url).status_code == 204
    assert owner.get(CAL + "?month=2026-11").json() == []
    assert owner.get(CAL + "?month=9999-12").status_code == 422
    assert owner.post(CAL, json={**body, "owner_id": "other"}).status_code == 422


def test_project_calendar_shared_without_exposing_personal_events_or_internal_fields(client):
    f, _, a, _, _, pid = connected(client)
    personal = f.post(
        CAL, json=dict(title="Secret errand", notes="Private personal note", scheduled_on="2026-11-20")
    )
    assert personal.status_code == 201
    task = f.post(
        f"/api/v1/projects/{pid}/tasks",
        json=dict(title="Shared milestone", due_date="2026-11-20", hourly_rate="70000", hours="5"),
    ).json()
    internal = f.post(f"/api/v1/projects/{pid}/tasks", json=dict(title="Internal undated note")).json()
    response = a.get(P + f"/projects/{pid}")
    assert response.status_code == 200
    tasks = response.json()["tasks"]
    assert [t["id"] for t in tasks] == [task["id"]]
    assert tasks[0]["client_visible"] is True
    assert "hourly_rate" not in tasks[0] and "checklist" not in tasks[0]
    assert "Secret errand" not in response.text and "Private personal note" not in response.text
    assert a.get(CAL + "?month=2026-11").json() == []
    # Even an explicit empty optional-publication list cannot hide a project calendar date.
    assert f.put(P + f"/projects/{pid}/published-tasks", json=dict(task_ids=[])).status_code == 200
    assert a.get(P + f"/projects/{pid}").json()["tasks"][0]["id"] == task["id"]
    f.patch(f"/api/v1/tasks/{task['id']}", json=dict(due_date="2026-12-01"))
    assert a.get(P + f"/projects/{pid}").json()["tasks"][0]["due_date"] == "2026-12-01"
    f.patch(f"/api/v1/tasks/{internal['id']}", json=dict(due_date="2026-12-02"))
    assert len(a.get(P + f"/projects/{pid}").json()["tasks"]) == 2
    outsider, _ = actor(client, "calendar-outsider@example.com")
    assert outsider.get(P + f"/projects/{pid}").status_code == 404
