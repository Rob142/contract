"""청구 후 수정 계약 반영 (계약_변경_반영_설계.md 9장)"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.clock import today
from app.db.session import get_engine
from tests.conftest import register
from tests.pdfs import text_pdf
from tests.test_contracts import CONTRACT_LINES, run_worker_once
from tests.test_invoices import (
    API,
    confirmed_contract,
    key,
    project_from_contract,
    stage_invoice,
    term_ids,
)

V2_TERMS = [
    {"key": "a", "stage": "deposit", "label": "선금", "amount": "500000", "requirement": "계약 체결 후"},
    {"key": "b", "stage": "interim", "label": "중도금", "amount": "300000", "requirement": "중간 검수 후"},
    {"key": "c", "stage": "balance", "label": "잔금", "amount": "400000", "requirement": "최종 검수 후"},
]


def upload_version(
    client: TestClient, contract_id: str, amount: str = "1200000", confirm: bool = True
) -> str:
    res = client.post(
        f"{API}/contracts/{contract_id}/versions",
        files={"file": ("revised.pdf", text_pdf([CONTRACT_LINES + ["Revised"]]), "application/pdf")},
    )
    assert res.status_code == 202, res.text
    assert res.json()["contract"]["version_no"] >= 2
    run_worker_once()
    if confirm:
        res = client.patch(
            f"{API}/contracts/{contract_id}/fields",
            json={
                "values": {
                    "contract_amount": amount,
                    "final_due_date": "2026-12-20",
                    "payment_terms": "계약 체결 후 선금 50%, 검수 완료 후 잔금 50%",
                },
                "confirm": True,
            },
        )
        assert res.status_code == 200, res.text
    return (
        res.json()["version_id"]
        if confirm
        else client.get(f"{API}/contracts/{contract_id}").json()["version_id"]
    )


def billed_deposit(client: TestClient) -> tuple[dict, dict]:
    """선금 50만 원을 발행·입금한 프로젝트"""
    register(client)
    project, _ = project_from_contract(client)
    terms = term_ids(client, project["id"])
    deposit = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "선금")
    assert client.post(f"{API}/invoices/{deposit['id']}/issue", json={}, headers=key()).status_code == 200
    res = client.post(
        f"{API}/invoices/{deposit['id']}/payments",
        json={"amount": "500000", "paid_on": today().isoformat()},
        headers=key(),
    )
    assert res.status_code == 201
    return project, deposit


def revise(client: TestClient, project: dict, version_id: str, **overrides: object):
    detail = client.get(f"{API}/projects/{project['id']}").json()
    old = {t["label"]: t["id"] for t in detail["payment_terms"]}
    body = {
        "contract_version_id": version_id,
        "version": detail["version"],
        "contract_amount": "1200000",
        "due_date": "2026-12-20",
        "payment_terms": V2_TERMS,
        "carry": [{"from_term_id": old.get("선금 50%") or old.get("선금"), "to_key": "a"}],
    }
    body.update(overrides)
    return client.post(f"{API}/projects/{project['id']}/revise-contract", json=body, headers=key())


def test_revision_carries_billing_into_new_stages(client: TestClient) -> None:
    project, deposit = billed_deposit(client)
    contract_id = project["contract_id"]

    # 수정 계약서를 같은 계약의 v2로 올리면, 계약은 계속 그 프로젝트에 연결된 것으로 보인다
    v2 = upload_version(client, contract_id)
    contract = client.get(f"{API}/contracts/{contract_id}").json()
    assert contract["version_no"] == 2 and contract["project_id"] == project["id"]
    assert contract["project_version_no"] == 1
    assert [v["version_no"] for v in contract["versions"]] == [2, 1]
    assert contract["previous_values"]["contract_amount"] == "1000000"

    draft = client.post(
        f"{API}/projects/{project['id']}/revision-draft", json={"contract_version_id": v2}
    ).json()
    assert draft["from_version"]["version_no"] == 1 and draft["to_version"]["contract_amount"] == "1200000"
    old = {t["label"]: t for t in draft["old_terms"]}
    assert old["선금 50%"]["must_carry"] and old["선금 50%"]["billed"] == "500000"
    assert old["선금 50%"]["invoices"][0]["id"] == deposit["id"]
    assert not old["잔금 50%"]["must_carry"]
    assert draft["proposed_carry"] == [{"from_term_id": old["선금 50%"]["term_id"], "to_key": "t1"}]

    res = revise(client, project, v2)
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["contract_amount"] == "1200000" and detail["due_date"] == "2026-12-20"
    terms = {t["label"]: t for t in detail["payment_terms"]}
    assert terms["선금"]["carried_amount"] == "500000" and terms["선금"]["billing_status"] == "paid"
    assert terms["중도금"]["billing_status"] == "unbilled"
    assert client.get(f"{API}/contracts/{contract_id}").json()["project_version_no"] == 2

    cands = {
        t["label"]: t
        for t in client.get(f"{API}/projects/{project['id']}/billing-candidates").json()["payment_terms"]
    }
    assert cands["선금"]["remaining_amount"] == "0" and cands["선금"]["carried_amount"] == "500000"
    assert cands["중도금"]["remaining_amount"] == "300000"

    # 받은 선금을 새 계약으로 다시 청구할 수 없다
    again = stage_invoice(client, project["id"], cands["선금"]["payment_term_id"], "1", "선금 재청구")
    res = client.post(f"{API}/invoices/{again['id']}/issue", json={}, headers=key())
    assert res.status_code == 409 and res.json()["error"]["code"] == "over_billed"
    # 중도금은 청구할 수 있다
    interim = stage_invoice(client, project["id"], cands["중도금"]["payment_term_id"], "300000", "중도금")
    assert client.post(f"{API}/invoices/{interim['id']}/issue", json={}, headers=key()).status_code == 200

    # 발행 기록과 입금은 그대로
    old_invoice = client.get(f"{API}/invoices/{deposit['id']}").json()
    assert old_invoice["status"] == "issued" and old_invoice["payment_status"] == "paid"

    # 청구가 이어졌으므로 연결 해제는 막힌다
    res = client.delete(f"{API}/projects/{project['id']}/contract")
    assert res.status_code == 409 and res.json()["error"]["code"] == "contract_has_billing"


def test_revision_validation(client: TestClient) -> None:
    project, _ = billed_deposit(client)
    contract_id = project["contract_id"]
    v1 = client.get(f"{API}/contracts/{contract_id}").json()["version_id"]
    v2 = upload_version(client, contract_id)

    def code(res) -> str:  # noqa: ANN001
        return res.json()["error"]["code"]

    assert code(revise(client, project, v2, carry=[])) == "carry_missing"
    res = revise(
        client,
        project,
        v2,
        payment_terms=[
            {"key": "a", "stage": "deposit", "label": "선금", "amount": "400000"},
            {"key": "c", "stage": "balance", "label": "잔금", "amount": "800000"},
        ],
    )
    assert code(res) == "carry_exceeds_term"
    res = revise(
        client,
        project,
        v2,
        contract_amount="400000",
        payment_terms=[{"key": "a", "stage": "deposit", "label": "선금", "amount": "400000"}],
    )
    assert res.status_code == 422 and code(res) == "amount_below_billed"
    terms = client.get(f"{API}/projects/{project['id']}").json()["payment_terms"]
    balance_id = next(t["id"] for t in terms if t["label"] == "잔금 50%")
    res = revise(client, project, v2, carry=[{"from_term_id": balance_id, "to_key": "c"}])
    assert code(res) in ("carry_missing", "carry_not_needed")
    assert code(revise(client, project, v1)) == "revision_not_newer"
    other = confirmed_contract(client)
    other_v = client.get(f"{API}/contracts/{other}").json()["version_id"]
    assert code(revise(client, project, other_v)) == "revision_other_contract"
    assert code(revise(client, project, v2, version="2020-01-01T00:00:00Z")) == "version_conflict"
    # 단계 합이 금액과 다르면 요청 자체가 잘못됐다
    assert revise(client, project, v2, contract_amount="1300000").status_code == 422

    # 같은 계약의 새 버전으로 새 프로젝트를 만들거나 "연결"할 수는 없다 (반영으로만)
    draft = client.post(f"{API}/contracts/{contract_id}/project-draft").json()
    assert draft["linked_project_id"] == project["id"]
    body = {
        "project_id": project["id"],
        "replace_contract": True,
        "name": "x",
        "job_type": "design",
        "contract_amount": "1200000",
        "payment_terms": [{"stage": "other", "label": "일시불", "amount": "1200000"}],
    }
    res = client.post(f"{API}/contracts/{contract_id}/project", json=body, headers=key())
    assert code(res) == "use_contract_revision"

    # 아무것도 바뀌지 않았다
    assert client.get(f"{API}/projects/{project['id']}").json()["contract_amount"] == "1000000"


def test_unconfirmed_version_and_busy_upload(client: TestClient) -> None:
    project, _ = billed_deposit(client)
    contract_id = project["contract_id"]
    res = client.post(
        f"{API}/contracts/{contract_id}/versions",
        files={"file": ("r.pdf", text_pdf([CONTRACT_LINES]), "application/pdf")},
    )
    assert res.status_code == 202
    v2 = res.json()["contract"]["version_id"]
    # 추출이 끝나기 전에는 또 올릴 수 없다
    res = client.post(
        f"{API}/contracts/{contract_id}/versions",
        files={"file": ("r.pdf", text_pdf([CONTRACT_LINES]), "application/pdf")},
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "version_in_progress"
    run_worker_once()
    res = client.post(f"{API}/projects/{project['id']}/revision-draft", json={"contract_version_id": v2})
    assert res.status_code == 409 and res.json()["error"]["code"] == "contract_not_confirmed"


def test_drafts_move_and_cancel_reissue_follow_lineage(client: TestClient) -> None:
    project, deposit = billed_deposit(client)
    terms = term_ids(client, project["id"])
    # 반영 전 잔금 초안
    balance_draft = stage_invoice(client, project["id"], terms["잔금 50%"], "400000", "잔금 초안")
    v2 = upload_version(client, project["contract_id"])
    detail = client.get(f"{API}/projects/{project['id']}").json()
    old = {t["label"]: t["id"] for t in detail["payment_terms"]}
    res = revise(
        client,
        project,
        v2,
        carry=[
            {"from_term_id": old["선금 50%"], "to_key": "a"},
            {"from_term_id": old["잔금 50%"], "to_key": "c"},
        ],
    )
    assert res.status_code == 200, res.text
    new = {t["label"]: t for t in res.json()["payment_terms"]}
    assert new["잔금"]["billing_status"] == "draft"

    # 초안은 새 잔금 단계로 옮겨져 그대로 발행된다
    moved = client.get(f"{API}/invoices/{balance_draft['id']}").json()
    assert moved["items"][0]["payment_term_id"] == new["잔금"]["id"]
    assert (
        client.post(f"{API}/invoices/{balance_draft['id']}/issue", json={}, headers=key()).status_code == 200
    )

    # 옛 선금 인보이스를 취소하면 이월이 줄어 새 선금을 청구할 수 있다
    payments = client.get(f"{API}/invoices/{deposit['id']}").json()["payments"]
    for p in payments:
        client.post(f"{API}/payments/{p['id']}/void", json={"reason": "입금 오류"})
    assert (
        client.post(f"{API}/invoices/{deposit['id']}/cancel", json={"reason": "금액 오류"}).status_code == 200
    )
    cands = {
        t["label"]: t
        for t in client.get(f"{API}/projects/{project['id']}/billing-candidates").json()["payment_terms"]
    }
    assert cands["선금"]["carried_amount"] == "0" and cands["선금"]["remaining_amount"] == "500000"

    # 재발행은 옛 선금이 아니라 이어진 새 선금으로 배분된다
    res = client.post(f"{API}/invoices/{deposit['id']}/reissue")
    assert res.status_code == 201, res.text
    assert res.json()["items"][0]["payment_term_id"] == new["선금"]["id"]


def test_lineage_spans_multiple_revisions(client: TestClient) -> None:
    project, _ = billed_deposit(client)
    contract_id = project["contract_id"]
    v2 = upload_version(client, contract_id)
    assert revise(client, project, v2).status_code == 200
    v3 = upload_version(client, contract_id)
    detail = client.get(f"{API}/projects/{project['id']}").json()
    deposit_v2 = next(t["id"] for t in detail["payment_terms"] if t["label"] == "선금")
    draft = client.post(
        f"{API}/projects/{project['id']}/revision-draft", json={"contract_version_id": v3}
    ).json()
    carried = next(t for t in draft["old_terms"] if t["term_id"] == deposit_v2)
    assert carried["must_carry"] and carried["billed"] == "500000"  # v1에서 v2로 이어진 청구

    res = revise(client, project, v3, carry=[{"from_term_id": deposit_v2, "to_key": "a"}])
    assert res.status_code == 200, res.text
    deposit_v3 = next(t for t in res.json()["payment_terms"] if t["label"] == "선금")
    assert deposit_v3["carried_amount"] == "500000"


def test_db_rejects_old_terms_and_lineage_over_billing(client: TestClient) -> None:
    project, deposit = billed_deposit(client)
    v1_deposit = term_ids(client, project["id"])["선금 50%"]
    v2 = upload_version(client, project["contract_id"])
    assert revise(client, project, v2).status_code == 200
    new = {t["label"]: t["id"] for t in client.get(f"{API}/projects/{project['id']}").json()["payment_terms"]}
    interim = stage_invoice(client, project["id"], new["중도금"], "300000", "중도금")

    engine = get_engine()
    with engine.begin() as conn:
        item_id = conn.execute(
            text("SELECT id FROM invoice_items WHERE invoice_id = :i"), {"i": interim["id"]}
        ).scalar_one()

    # 옛 계약의 단계로는 배분할 수 없다
    with pytest.raises(DBAPIError, match="current contract version"), engine.begin() as conn:
        conn.execute(
            text("UPDATE billing_allocations SET payment_term_id = :t WHERE invoice_item_id = :i"),
            {"t": v1_deposit, "i": item_id},
        )

    # 서비스를 거치지 않아도 계보 전체로 한도를 검사한다: 이월로 꽉 찬 새 선금에 1원 더 발행
    with pytest.raises(DBAPIError, match="over-billed"), engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE billing_allocations SET payment_term_id = :t, amount = 1 WHERE invoice_item_id = :i"
            ),
            {"t": new["선금"], "i": item_id},
        )
        conn.execute(
            text("UPDATE invoice_items SET quantity = 1, unit_price = 1, amount = 1 WHERE id = :i"),
            {"i": item_id},
        )
        conn.execute(
            text(
                "UPDATE invoices SET subtotal = 1, total = 1, status = 'issued', invoice_no = 'X-1',"
                " issue_date = current_date, issued_at = now(), snapshot = '{}'::jsonb WHERE id = :i"
            ),
            {"i": interim["id"]},
        )

    # 승계 기록은 고칠 수 없다
    with pytest.raises(DBAPIError, match="cannot be modified"), engine.begin() as conn:
        conn.execute(text("UPDATE payment_term_successions SET created_at = now()"))
    assert deposit["id"]


def test_dashboard_suggests_pending_revision(client: TestClient) -> None:
    project, _ = billed_deposit(client)
    upload_version(client, project["contract_id"])
    todos = client.get(f"{API}/dashboard").json()["todos"]
    todo = next(t for t in todos if t["kind"] == "contract_revision")
    assert todo["target"] == "project_revision" and todo["target_id"] == project["id"]
    assert "v1 → v2" in todo["detail"]


def test_delete_latest_version_restores_previous(client: TestClient) -> None:
    """수정본(최신 버전)만 지우면 이전 버전이 다시 현재가 되고, 계약과 v1 원본은 남는다"""
    from app.core.storage import get_storage

    register(client)
    contract_id = confirmed_contract(client)

    # 하나뿐인 버전은 지울 수 없다 (계약 삭제를 써야 한다)
    res = client.delete(f"{API}/contracts/{contract_id}/versions/1")
    assert res.status_code == 409 and res.json()["error"]["code"] == "only_version"

    res = client.post(
        f"{API}/contracts/{contract_id}/versions",
        files={"file": ("revised.pdf", text_pdf([CONTRACT_LINES + ["Revised"]]), "application/pdf")},
    )
    assert res.status_code == 202
    # 추출 중에는 지울 수 없다
    res = client.delete(f"{API}/contracts/{contract_id}/versions/2")
    assert res.status_code == 409 and res.json()["error"]["code"] == "contract_busy"
    run_worker_once()

    with get_engine().connect() as conn:
        v2_key = conn.execute(
            text(
                "SELECT f.object_key FROM files f JOIN contract_versions cv ON cv.file_id = f.id "
                "WHERE cv.version_no = 2"
            )
        ).scalar_one()

    # 최신이 아닌 버전, 없는 버전은 지울 수 없다
    res = client.delete(f"{API}/contracts/{contract_id}/versions/1")
    assert res.status_code == 409 and res.json()["error"]["code"] == "version_not_latest"
    assert client.delete(f"{API}/contracts/{contract_id}/versions/9").status_code == 404

    res = client.delete(f"{API}/contracts/{contract_id}/versions/2")
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["version_no"] == 1 and detail["status"] == "ready"
    assert [v["version_no"] for v in detail["versions"]] == [1]
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM contract_versions")).scalar() == 1
        assert conn.execute(text("SELECT count(*) FROM files")).scalar() == 1
    with pytest.raises(FileNotFoundError):
        get_storage().open(v2_key)
    assert client.get(f"{API}/contracts/{contract_id}/file").status_code == 200

    # 다시 올리면 v2 번호를 다시 쓴다
    upload_version(client, contract_id)
    assert client.get(f"{API}/contracts/{contract_id}").json()["version_no"] == 2


def test_delete_version_blocked_when_applied_or_foreign(client: TestClient) -> None:
    project, _ = billed_deposit(client)
    contract_id = project["contract_id"]
    v2 = upload_version(client, contract_id)
    assert revise(client, project, v2).status_code == 200

    # 프로젝트에 반영한 버전은 지울 수 없다
    res = client.delete(f"{API}/contracts/{contract_id}/versions/2")
    assert res.status_code == 409 and res.json()["error"]["code"] == "version_in_use"

    # 다른 사용자에게는 존재도 드러내지 않는다
    client.post(f"{API}/auth/logout")
    register(client, email="other@example.com")
    assert client.delete(f"{API}/contracts/{contract_id}/versions/2").status_code == 404
