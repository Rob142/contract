"""진행 현황 공유: 템플릿, 공유 링크, 클라이언트 공개 API, 피드백, 수정 카운터, 첨부."""

import io
import threading

from fastapi.testclient import TestClient

from app.api.routes.public import get_write_limiter
from tests.conftest import register
from tests.test_projects import add_task, make_project

API = "/api/v1"


def setup_shared(client: TestClient, **project: object) -> tuple[dict, str]:
    register(client)
    p = make_project(client, **project)
    res = client.post(f"{API}/projects/{p['id']}/share-link")
    assert res.status_code == 201, res.text
    return p, res.json()["token"]


def pub(token: str, path: str = "") -> str:
    return f"{API}/public/p/{token}{path}"


def anon(client: TestClient) -> TestClient:
    """로그인 쿠키 없는 클라이언트 (공유 링크를 받은 사람)"""
    other = TestClient(client.app)
    other.headers.update({"origin": "http://testserver"})
    return other


def test_template_creates_steps_by_job_type(client: TestClient) -> None:
    register(client)
    p = make_project(client, use_template=True)  # 사용자 기본 직군 = design
    tasks = client.get(f"{API}/projects/{p['id']}/tasks").json()
    assert [t["title"] for t in tasks] == ["착수·자료 수령", "시안 제작", "수정", "최종 납품"]
    assert {t["source"] for t in tasks} == {"template"}
    assert make_project(client, use_template=False)["total_tasks"] == 0
    templates = {t["job_type"]: t["steps"] for t in client.get(f"{API}/job-templates").json()}
    assert set(templates) == {
        "dev",
        "design",
        "video",
        "marketing",
        "writing",
        "translation",
        "education",
        "consulting",
        "photography",
        "other",
    }


def test_share_link_lifecycle(client: TestClient) -> None:
    p, token = setup_shared(client)
    state = client.get(f"{API}/projects/{p['id']}/share-link").json()["link"]
    assert state["token"] is None  # 원문은 만들 때 한 번만
    assert client.post(f"{API}/projects/{p['id']}/share-link").status_code == 409

    visitor = anon(client)
    assert visitor.get(pub(token)).status_code == 200

    # 재발급하면 이전 링크는 즉시 무효
    new = client.post(f"{API}/projects/{p['id']}/share-link/regenerate").json()["token"]
    assert visitor.get(pub(token)).status_code == 404
    assert visitor.get(pub(new)).status_code == 200

    assert client.delete(f"{API}/projects/{p['id']}/share-link").status_code == 204
    assert visitor.get(pub(new)).status_code == 404
    assert visitor.get(pub("not-a-real-token")).status_code == 404  # 없음도 같은 404


def test_expired_link_is_not_found(client: TestClient) -> None:
    p, token = setup_shared(client)
    res = client.patch(f"{API}/projects/{p['id']}/share-link", json={"expires_at": "2020-01-01T00:00:00Z"})
    assert res.status_code == 200
    assert anon(client).get(pub(token)).status_code == 404


def test_public_view_is_allow_list_only(client: TestClient) -> None:
    p, token = setup_shared(client, included_revisions=2)
    add_task(client, p["id"], "시안 제작", hours="3", hourly_rate="50000")
    res = anon(client).get(pub(token))
    assert res.status_code == 200
    assert res.headers["x-robots-tag"] == "noindex, nofollow"
    assert res.headers["referrer-policy"] == "no-referrer"
    body = res.json()
    assert body["contract"]["contract_amount"] == "1000000"
    assert body["revision"] == {"included": 2, "used": 0, "remaining": 2}
    assert body["invoices"] is None  # 기본은 인보이스 숨김
    raw = res.text
    for secret in ("hourly_rate", "50000", "jiyoon@example.com", "owner_id", "client"):
        assert secret not in raw, secret


def test_view_events_record_open_and_ack(client: TestClient) -> None:
    p, token = setup_shared(client)
    task = add_task(client, p["id"], "시안 제작")
    visitor = anon(client)
    visitor.get(pub(token))
    assert (
        visitor.post(pub(token, f"/tasks/{task['id']}/ack"), json={"viewer_name": "박대리"}).status_code
        == 204
    )
    kinds = [
        (e["kind"], e["viewer_name"]) for e in client.get(f"{API}/projects/{p['id']}/view-events").json()
    ]
    assert ("open", None) in kinds and ("stage_ack", "박대리") in kinds
    assert client.get(f"{API}/projects/{p['id']}/share-link").json()["link"]["last_viewed_at"] is not None
    # 다른 프로젝트의 단계는 확인할 수 없다
    other = make_project(client, name="다른 프로젝트")
    foreign = add_task(client, other["id"], "남의 단계")
    assert visitor.post(pub(token, f"/tasks/{foreign['id']}/ack"), json={}).status_code == 404


def test_feedback_is_append_only_and_shared(client: TestClient) -> None:
    p, token = setup_shared(client)
    task = add_task(client, p["id"], "시안 제작")
    visitor = anon(client)
    res = visitor.post(
        pub(token, f"/tasks/{task['id']}/feedback"),
        json={"body": "로고를 키워 주세요", "author_name": "박대리"},
    )
    assert res.status_code == 201 and res.json()["author_role"] == "client"
    assert client.post(f"{API}/tasks/{task['id']}/feedback", json={"body": "반영했어요"}).status_code == 201

    feedback = visitor.get(pub(token)).json()["tasks"][0]["feedback"]
    assert [f["author_role"] for f in feedback] == ["client", "freelancer"]
    assert len(client.get(f"{API}/projects/{p['id']}/feedback").json()) == 2

    # DB 수준에서도 수정할 수 없다
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.db.session import get_engine

    try:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE task_feedback SET body = '바꿈'"))
    except DBAPIError:
        pass
    else:
        raise AssertionError("task_feedback must be append-only")

    # 피드백을 끄면 클라이언트는 쓸 수 없다
    client.patch(f"{API}/projects/{p['id']}/share-link", json={"allow_feedback": False})
    assert visitor.post(pub(token, f"/tasks/{task['id']}/feedback"), json={"body": "x"}).status_code == 403


def test_revision_counter_flow(client: TestClient) -> None:
    p, token = setup_shared(client, included_revisions=2)
    visitor = anon(client)
    for i in range(3):
        res = visitor.post(pub(token, "/revision-requests"), json={"body": f"수정 {i + 1}"})
        assert res.status_code == 201
        assert res.json()["seq"] == i + 1
        assert res.json()["over_limit"] is (i >= 2)  # 3번째부터 포함 횟수 초과

    state = client.get(f"{API}/projects/{p['id']}/revisions").json()
    assert state["counter"] == {"included": 2, "used": 3, "remaining": 0}
    over = state["requests"][2]

    # 취소·카운트 제외는 사유가 필요하고, 기록은 남는다
    res = client.post(f"{API}/revision-requests/{over['id']}/exclude", json={"reason": "단순 오타 정정"})
    assert res.status_code == 200
    assert res.json()["counter"]["used"] == 2 and len(res.json()["requests"]) == 3

    quote = client.post(
        f"{API}/projects/{p['id']}/extra-quotes",
        json={"title": "추가 수정 1회", "amount": "50000", "revision_request_id": over["id"]},
    )
    assert quote.status_code == 201 and quote.json()["amount"] == "50000"
    assert len(client.get(f"{API}/projects/{p['id']}/revisions").json()["quotes"]) == 1


def test_excluding_an_earlier_request_clears_over_limit_flag(client: TestClient) -> None:
    """앞선 요청을 카운트에서 빼면, 그 덕에 포함 횟수 안에 들어온 요청의 초과 표시가 사라진다."""
    p, token = setup_shared(client, included_revisions=2)
    visitor = anon(client)
    for i in range(3):
        visitor.post(pub(token, "/revision-requests"), json={"body": f"수정 {i + 1}"})
    requests = client.get(f"{API}/projects/{p['id']}/revisions").json()["requests"]
    assert [r["over_limit"] for r in requests] == [False, False, True]

    state = client.post(
        f"{API}/revision-requests/{requests[0]['id']}/exclude", json={"reason": "방향 확인 요청"}
    ).json()
    assert [r["over_limit"] for r in state["requests"]] == [False, False, False]
    assert state["counter"] == {"included": 2, "used": 2, "remaining": 0}
    # 클라이언트 화면에도 같은 값이 보인다
    public = visitor.get(pub(token)).json()
    assert [r["over_limit"] for r in public["revision_requests"]] == [False, False, False]
    # 새 요청은 다시 초과로 접수된다
    assert (
        visitor.post(pub(token, "/revision-requests"), json={"body": "수정 4"}).json()["over_limit"] is True
    )


def test_template_steps_get_spread_due_dates(client: TestClient) -> None:
    register(client)
    p = make_project(client, use_template=True, start_date="2026-11-02", due_date="2026-12-15")
    tasks = client.get(f"{API}/projects/{p['id']}/tasks").json()
    dues = [t["due_date"] for t in tasks]
    assert dues[-1] == "2026-12-15"  # 마지막 단계는 납기와 같다
    assert dues == sorted(dues) and len(set(dues)) == len(dues)
    assert all("2026-11-02" < d <= "2026-12-15" for d in dues)

    no_dates = make_project(client, use_template=True, start_date=None, due_date=None)
    assert {t["due_date"] for t in client.get(f"{API}/projects/{no_dates['id']}/tasks").json()} == {None}


def test_revision_counter_off_without_included_count(client: TestClient) -> None:
    _, token = setup_shared(client)
    visitor = anon(client)
    res = visitor.post(pub(token, "/revision-requests"), json={"body": "수정해 주세요"})
    assert res.json()["over_limit"] is False
    assert visitor.get(pub(token)).json()["revision"] == {"included": None, "used": 1, "remaining": None}


def test_concurrent_revision_requests_get_unique_seq(client: TestClient) -> None:
    p, token = setup_shared(client, included_revisions=10)
    get_write_limiter().reset()
    results: list[int] = []

    def send() -> None:
        res = anon(client).post(pub(token, "/revision-requests"), json={"body": "동시 요청"})
        results.append(res.json()["seq"])

    threads = [threading.Thread(target=send) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(results) == [1, 2, 3, 4, 5, 6]


def test_public_write_rate_limit(client: TestClient) -> None:
    _, token = setup_shared(client)
    visitor = anon(client)
    get_write_limiter().reset()
    codes = [
        visitor.post(pub(token, "/revision-requests"), json={"body": "x"}).status_code for _ in range(32)
    ]
    assert codes[:30] == [201] * 30 and codes[30] == 429
    get_write_limiter().reset()


def test_attachments_link_file_and_public_deliverables(client: TestClient) -> None:
    p, token = setup_shared(client)
    task = add_task(client, p["id"], "최종 납품")
    base = f"{API}/projects/{p['id']}/attachments"

    bad = client.post(f"{base}/link", json={"title": "x", "url": "javascript:alert(1)"})
    assert bad.status_code == 422
    link = client.post(
        f"{base}/link", json={"title": "시안 v1", "url": "https://example.com/a", "task_id": task["id"]}
    )
    assert link.status_code == 201

    res = client.post(
        f"{base}/file",
        files={"file": ("final.zip", io.BytesIO(b"PK\x03\x04data"), "application/zip")},
        data={"task_id": task["id"], "kind": "deliverable"},
    )
    assert res.status_code == 201 and res.json()["has_file"] is True
    att_id = res.json()["id"]
    exe = client.post(
        f"{base}/file", files={"file": ("evil.exe", io.BytesIO(b"MZ"), "application/octet-stream")}
    )
    assert exe.status_code == 422

    # 소유자 다운로드
    dl = client.get(f"{API}/attachments/{att_id}/file")
    assert dl.status_code == 200 and dl.content == b"PK\x03\x04data"
    assert dl.headers["cache-control"] == "no-store" and "attachment" in dl.headers["content-disposition"]

    # 클라이언트는 결과물만 본다
    visitor = anon(client)
    deliverables = visitor.get(pub(token)).json()["tasks"][0]["deliverables"]
    assert {d["title"] for d in deliverables} == {"시안 v1", "final.zip"}
    assert visitor.get(pub(token, f"/attachments/{att_id}/file")).content == b"PK\x03\x04data"

    evidence = client.post(
        f"{base}/file",
        files={"file": ("receipt.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")},
        data={"kind": "evidence", "doc_type": "receipt"},
    ).json()
    assert visitor.get(pub(token, f"/attachments/{evidence['id']}/file")).status_code == 404

    assert len(client.get(f"{base}?kind=evidence").json()) == 1
    assert client.delete(f"{API}/attachments/{att_id}").status_code == 204
    assert client.get(f"{API}/attachments/{att_id}/file").status_code == 404


def test_other_owners_cannot_touch_sharing(client: TestClient) -> None:
    p, _ = setup_shared(client)
    att = client.post(
        f"{API}/projects/{p['id']}/attachments/link", json={"title": "a", "url": "https://example.com"}
    ).json()
    client.cookies.clear()
    register(client, email="other@example.com")
    assert client.get(f"{API}/projects/{p['id']}/share-link").status_code == 404
    assert client.delete(f"{API}/projects/{p['id']}/share-link").status_code == 404
    assert client.get(f"{API}/projects/{p['id']}/attachments").status_code == 404
    assert client.delete(f"{API}/attachments/{att['id']}").status_code == 404
    assert client.get(f"{API}/projects/{p['id']}/revisions").status_code == 404
