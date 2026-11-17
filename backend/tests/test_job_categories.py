import pytest
from fastapi.testclient import TestClient

from app.analysis.rules import COMMON, rules_for
from tests.test_projects import make_project


@pytest.mark.parametrize(
    "job_type", ["writing", "translation", "education", "consulting", "photography", "other"]
)
def test_new_job_registration_and_project(client: TestClient, job_type: str) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "테스트 사용자",
            "email": "category@example.com",
            "password": "password123",
            "job_type": job_type,
            "agree_terms": True,
        },
    )
    assert response.status_code == 201
    assert response.json()["job_type"] == job_type
    project = make_project(client, use_template=True)
    assert project["job_type"] == job_type
    tasks = client.get(f"/api/v1/projects/{project['id']}/tasks").json()
    assert len(tasks) >= 3
    assert rules_for(job_type) == COMMON
    # Reusing a saved client must not create another client record.
    second = make_project(client, client_id=project["client"]["id"], new_client_name=None)
    assert second["client"]["id"] == project["client"]["id"]
    assert len(client.get("/api/v1/clients").json()) == 1
