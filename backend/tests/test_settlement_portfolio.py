"""정산(월별 수입·증빙)과 포트폴리오."""

import io

from fastapi.testclient import TestClient

from app.core.clock import today
from tests.conftest import register
from tests.test_invoices import key, project_from_contract, stage_invoice, term_ids
from tests.test_projects import add_task, make_project
from tests.test_sharing import anon, pub

API = "/api/v1"


def paid_invoice(client: TestClient) -> dict:
    project, _ = project_from_contract(client)
    terms = term_ids(client, project["id"])
    inv = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "디자인 선금")
    assert client.post(f"{API}/invoices/{inv['id']}/issue", json={}, headers=key()).status_code == 200
    res = client.post(
        f"{API}/invoices/{inv['id']}/payments",
        json={"amount": "300000", "paid_on": today().isoformat()},
        headers=key(),
    )
    assert res.status_code == 201
    return {"project": project, "invoice": inv, "payment_id": res.json()["payments"][0]["id"]}


# ---------------------------------------------------------------- 정산
def test_monthly_income_counts_received_by_payment_date(client: TestClient) -> None:
    register(client)
    ctx = paid_invoice(client)
    this_month = today().strftime("%Y-%m")

    data = client.get(f"{API}/settlement/monthly-income?months=3").json()
    assert [m["month"] for m in data["months"]][-1] == this_month and len(data["months"]) == 3
    current = data["months"][-1]
    assert current["received"] == "300000"  # 입금일 기준 입금액
    assert current["billed"] == "500000"  # 발행 기준 청구액은 따로
    assert data["months"][0]["received"] == "0"  # 입금 없는 달도 0으로 채운다

    detail = client.get(f"{API}/settlement/monthly-income/{this_month}").json()
    assert detail["received"] == "300000" and detail["projects"][0]["project_id"] == ctx["project"]["id"]
    assert client.get(f"{API}/dashboard").json()["received_this_month"] == "300000"

    # 취소된 입금은 수입에서 빠진다
    assert (
        client.post(f"{API}/payments/{ctx['payment_id']}/void", json={"reason": "오입력"}).status_code == 200
    )
    assert client.get(f"{API}/settlement/monthly-income?months=1").json()["months"][0]["received"] == "0"
    assert client.get(f"{API}/dashboard").json()["received_this_month"] == "0"
    assert client.get(f"{API}/settlement/monthly-income/2026-13").status_code == 422


def test_monthly_income_is_owner_scoped(client: TestClient) -> None:
    register(client)
    paid_invoice(client)
    client.cookies.clear()
    register(client, email="other@example.com")
    data = client.get(f"{API}/settlement/monthly-income?months=1").json()
    assert data["received_total"] == "0" and data["billed_total"] == "0"


def test_evidence_upload_and_filters(client: TestClient) -> None:
    register(client)
    a = make_project(client)
    b = make_project(client, name="두번째 프로젝트")
    files = {"file": ("세금계산서.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")}
    res = client.post(
        f"{API}/projects/{a['id']}/attachments/file",
        files=files,
        data={"kind": "evidence", "doc_type": "tax_invoice", "issued_on": "2026-11-05", "amount": "550000"},
    )
    assert (
        res.status_code == 201
        and res.json()["amount"] == "550000"
        and res.json()["issued_on"] == "2026-11-05"
    )
    client.post(
        f"{API}/projects/{b['id']}/attachments/link",
        json={"title": "홈택스 링크", "url": "https://example.com/x", "kind": "evidence"},
    )

    assert len(client.get(f"{API}/settlement/evidence").json()) == 2
    only_a = client.get(f"{API}/settlement/evidence?project_id={a['id']}").json()
    assert [e["title"] for e in only_a] == ["세금계산서.pdf"] and only_a[0]["project_name"] == a["name"]
    assert len(client.get(f"{API}/settlement/evidence?doc_type=tax_invoice").json()) == 1
    assert len(client.get(f"{API}/settlement/evidence?month=2026-11").json()) == 1
    assert client.get(f"{API}/settlement/evidence?month=2026-10").json() == []


# ---------------------------------------------------------------- 포트폴리오
def completed_project(client: TestClient) -> tuple[dict, str, str]:
    p = make_project(client, included_revisions=2)
    task = add_task(client, p["id"], "최종 납품")
    client.post(f"{API}/tasks/{task['id']}/move", json={"status": "done", "index": 0})
    att = client.post(
        f"{API}/projects/{p['id']}/attachments/link",
        json={"title": "최종 시안", "url": "https://example.com/final", "task_id": task["id"]},
    ).json()
    client.post(
        f"{API}/projects/{p['id']}/attachments/link",
        json={"title": "내부 메모", "url": "https://example.com/m", "kind": "other"},
    )
    link = client.post(f"{API}/projects/{p['id']}/share-link").json()
    fb = (
        anon(client)
        .post(
            pub(link["token"], f"/tasks/{task['id']}/feedback"),
            json={"body": "아주 만족스러워요", "author_name": "박대리"},
        )
        .json()
    )
    client.patch(f"{API}/projects/{p['id']}", json={"status": "completed"})
    return p, att["id"], fb["id"]


def test_draft_collects_deliverables_period_and_client_feedback(client: TestClient) -> None:
    register(client)
    p, att_id, fb_id = completed_project(client)
    draft = client.post(f"{API}/projects/{p['id']}/portfolio-draft").json()
    assert draft["project_completed"] is True and draft["job_type"] == "design"
    assert [a["attachment_id"] for a in draft["assets"]] == [att_id]  # 결과물만, 내부 메모 제외
    assert draft["quote_candidates"][0]["feedback_id"] == fb_id
    assert draft["period_start"] == "2026-11-12"
    assert client.get(f"{API}/portfolio").json()["items"] == []  # 저장하지 않는다


def test_portfolio_visibility_consent_and_public_view(client: TestClient) -> None:
    register(client)
    p, att_id, fb_id = completed_project(client)
    created = client.post(
        f"{API}/portfolio",
        json={
            "project_id": p["id"],
            "title": "모노 스튜디오 브랜드 리뉴얼",
            "description": "로고와 가이드 제작",
            "asset_ids": [att_id],
            "cover_attachment_id": att_id,
            "quotes": [{"feedback_id": fb_id, "quote": "아주 만족스러워요"}],
        },
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["status"] == "draft" and item["visibility"] == "private" and item["share_slug"] is None
    assert client.post(f"{API}/portfolio", json={"project_id": p["id"], "title": "중복"}).status_code == 409

    # 준비 전에는 공개할 수 없다
    res = client.patch(f"{API}/portfolio/{item['id']}", json={"visibility": "link"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "portfolio_not_ready"

    res = client.patch(f"{API}/portfolio/{item['id']}", json={"status": "ready", "visibility": "link"})
    assert res.status_code == 200
    slug = res.json()["share_slug"]
    assert slug

    visitor = anon(client)
    body = visitor.get(f"{API}/public/portfolio/{slug}").json()
    assert body["title"] == "모노 스튜디오 브랜드 리뉴얼" and body["freelancer_name"] == "김지윤"
    assert body["client_name"] is None  # 클라이언트명은 기본 비공개
    assert body["quotes"] == []  # 동의 확인 전에는 인용을 내보내지 않는다
    raw = visitor.get(f"{API}/public/portfolio/{slug}").text
    for secret in ("1000000", "contract_amount", '모노 스튜디오"', "박대리"):
        assert secret not in raw, secret

    client.patch(f"{API}/portfolio/{item['id']}", json={"feedback_consent": True, "show_client_name": True})
    body = visitor.get(f"{API}/public/portfolio/{slug}").json()
    assert body["client_name"] == "모노 스튜디오"
    assert body["quotes"] == [{"quote": "아주 만족스러워요", "author": "클라이언트"}]  # 이름은 기본 익명

    client.patch(
        f"{API}/portfolio/{item['id']}",
        json={"quotes": [{"feedback_id": fb_id, "quote": "아주 만족스러워요", "anonymize": False}]},
    )
    assert visitor.get(f"{API}/public/portfolio/{slug}").json()["quotes"][0]["author"] == "박대리"

    # 비공개로 되돌리거나 준비 상태를 내리면 즉시 404
    client.patch(f"{API}/portfolio/{item['id']}", json={"status": "draft"})
    assert visitor.get(f"{API}/public/portfolio/{slug}").status_code == 404
    assert client.get(f"{API}/portfolio/{item['id']}").json()["visibility"] == "private"
    assert visitor.get(f"{API}/public/portfolio/unknown-slug").status_code == 404


def test_portfolio_rejects_foreign_assets_and_other_owners(client: TestClient) -> None:
    register(client)
    p, att_id, fb_id = completed_project(client)
    other_project = make_project(client, name="다른 프로젝트")
    foreign = client.post(
        f"{API}/projects/{other_project['id']}/attachments/link",
        json={"title": "남의 결과물", "url": "https://example.com/z"},
    ).json()
    body = {"project_id": p["id"], "title": "카드", "asset_ids": [foreign["id"]]}
    assert client.post(f"{API}/portfolio", json=body).status_code == 404  # 다른 프로젝트 결과물은 못 쓴다

    item = client.post(
        f"{API}/portfolio", json={"project_id": p["id"], "title": "카드", "asset_ids": [att_id]}
    ).json()
    client.patch(f"{API}/portfolio/{item['id']}", json={"status": "ready", "visibility": "public"})
    slug = client.get(f"{API}/portfolio/{item['id']}").json()["share_slug"]
    assert (
        anon(client).get(f"{API}/public/portfolio/{slug}/assets/{att_id}/file").status_code == 404
    )  # 링크 첨부는 파일 없음

    client.cookies.clear()
    register(client, email="other@example.com")
    assert client.get(f"{API}/portfolio/{item['id']}").status_code == 404
    assert client.delete(f"{API}/portfolio/{item['id']}").status_code == 404
    assert client.post(f"{API}/projects/{p['id']}/portfolio-draft").status_code == 404
    assert client.get(f"{API}/portfolio").json()["items"] == []
