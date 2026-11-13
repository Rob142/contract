import uuid
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.clock import today
from app.db.session import get_engine
from app.services.payment_terms import parse_payment_terms, split_amount
from tests.conftest import register
from tests.pdfs import text_pdf
from tests.test_contracts import CONTRACT_LINES, run_worker_once, upload

API = "/api/v1"


def key() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


def confirmed_contract(
    client: TestClient, amount: str = "1000000", terms: str = "계약 체결 후 선금 50%, 검수 완료 후 잔금 50%"
) -> str:
    contract_id = upload(client, text_pdf([CONTRACT_LINES]), title="브랜드 디자인 용역 계약서").json()[
        "contract"
    ]["id"]
    run_worker_once()
    res = client.patch(
        f"{API}/contracts/{contract_id}/fields",
        json={
            "values": {"contract_amount": amount, "final_due_date": "2026-11-20", "payment_terms": terms},
            "confirm": True,
        },
    )
    assert res.status_code == 200, res.text
    return contract_id


def project_from_contract(client: TestClient) -> tuple[dict, dict]:
    contract_id = confirmed_contract(client)
    draft = client.post(f"{API}/contracts/{contract_id}/project-draft").json()
    body = {
        "name": draft["name"],
        "new_client_name": "모노 스튜디오",
        "job_type": draft["job_type"],
        "start_date": draft["start_date"],
        "due_date": draft["due_date"],
        "contract_amount": draft["contract_amount"],
        "payment_terms": [
            {k: t[k] for k in ("stage", "label", "ratio", "amount", "requirement")}
            for t in draft["payment_terms"]
        ],
        "tasks": [{"title": "로고 시안"}, {"title": "최종 납품"}],
    }
    res = client.post(f"{API}/contracts/{contract_id}/project", json=body, headers=key())
    assert res.status_code == 201, res.text
    return res.json(), draft


def term_ids(client: TestClient, project_id: str) -> dict[str, str]:
    cands = client.get(f"{API}/projects/{project_id}/billing-candidates").json()
    return {t["label"]: t["payment_term_id"] for t in cands["payment_terms"]}


def stage_invoice(
    client: TestClient, project_id: str, term_id: str, amount: str, title: str, confirm: bool = True
) -> dict:
    res = client.post(
        f"{API}/invoices",
        json={
            "project_id": project_id,
            "title": title,
            "due_date": (today() + timedelta(days=8)).isoformat(),
            "items": [
                {
                    "kind": "payment_stage",
                    "description": "브랜드 디자인 최종 납품",
                    "detail": "로고 · 브랜드 가이드 · 최종 파일 인도",
                    "unit_price": amount,
                    "payment_term_id": term_id,
                    "basis_note": "최종 납품 및 검수 확인",
                    "basis_confirmed": confirm,
                }
            ],
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


# ---------------------------------------------------------------- 지급 조건 나누기 (단위)
def test_extracted_terms_round_trip_into_stages_with_requirements() -> None:
    from app.extraction.fields import TextLine, find_fields

    line = TextLine("p1-b005", "계약 체결 후 선금 50%, 검수 완료 후 잔금 50%를 지급한다.")
    value = next(f.value for f in find_fields([line]) if f.key == "payment_terms")
    terms = parse_payment_terms(value, Decimal(1000000))
    assert [(t.label, t.requirement) for t in terms] == [
        ("선금 50%", "계약 체결 후"),
        ("잔금 50%", "검수 완료 후"),
    ]


def test_terms_with_trailing_requirements_become_stages() -> None:
    from app.extraction.fields import TextLine, find_fields

    lines = [
        TextLine(
            "a",
            "2. 선금은 총 계약 금액의 50%인 500,000원으로 하며, 계약 체결일로부터 3영업일 이내에 지급한다.",
        ),
        TextLine(
            "b", "3. 잔금은 총 계약 금액의 50%인 500,000원으로 하며, 검수 완료일로부터 7일 이내에 지급한다."
        ),
    ]
    value = next(f.value for f in find_fields(lines) if f.key == "payment_terms")
    terms = parse_payment_terms(value, Decimal(1000000))
    assert [(t.stage, t.amount, t.requirement) for t in terms] == [
        ("deposit", Decimal(500000), "계약 체결일로부터 3영업일 이내"),
        ("balance", Decimal(500000), "검수 완료일로부터 7일 이내"),
    ]


def test_parse_payment_terms_splits_amount_exactly() -> None:
    terms = parse_payment_terms("계약 체결 후 선금 50%, 검수 완료 후 잔금 50%", Decimal(1000000))
    assert [(t.stage, t.label, t.amount, t.requirement) for t in terms] == [
        ("deposit", "선금 50%", Decimal(500000), "계약 체결 후"),
        ("balance", "잔금 50%", Decimal(500000), "검수 완료 후"),
    ]
    # 나누어떨어지지 않아도 합계는 계약 금액과 같다 (나머지는 마지막 단계)
    assert split_amount(Decimal(1000000), [Decimal(30), Decimal(30), Decimal(40)]) == [
        Decimal(300000),
        Decimal(300000),
        Decimal(400000),
    ]
    odd = split_amount(Decimal(100), [Decimal(33), Decimal(33), Decimal(34)])
    assert sum(odd) == 100
    assert parse_payment_terms("세부 사항은 협의", Decimal(1)) == []


# ---------------------------------------------------------------- 계약서 → 프로젝트 (07)
def test_project_from_contract(client: TestClient) -> None:
    register(client)
    project, draft = project_from_contract(client)
    assert draft["contract_amount"] == "1000000"
    assert [t["label"] for t in draft["payment_terms"]] == ["선금 50%", "잔금 50%"]
    assert project["has_contract"] is True
    assert [(t["label"], t["amount"], t["requirement"]) for t in project["payment_terms"]] == [
        ("선금 50%", "500000", "계약 체결 후"),
        ("잔금 50%", "500000", "검수 완료 후"),
    ]
    assert project["total_tasks"] == 2

    contract_id = client.get(f"{API}/contracts").json()["items"][0]["id"]
    assert client.get(f"{API}/contracts/{contract_id}").json()["project_id"] == project["id"]
    # 같은 계약 버전으로 두 번째 프로젝트는 만들 수 없다 (같은 지급 단계 중복 청구 방지)
    again = client.post(
        f"{API}/contracts/{contract_id}/project",
        json={
            "name": "x",
            "new_client_name": "c",
            "job_type": "design",
            "contract_amount": "1000000",
            "payment_terms": [{"stage": "other", "label": "일시불", "amount": "1000000"}],
        },
        headers=key(),
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "contract_already_linked"


def test_project_from_contract_validation(client: TestClient) -> None:
    register(client)
    contract_id = upload(client, text_pdf([CONTRACT_LINES])).json()["contract"]["id"]
    run_worker_once()
    assert client.post(f"{API}/contracts/{contract_id}/project-draft").status_code == 409  # 확인 전

    contract_id = confirmed_contract(client)
    body = {
        "name": "x",
        "new_client_name": "c",
        "job_type": "design",
        "contract_amount": "1000000",
        "payment_terms": [{"stage": "deposit", "label": "선금", "amount": "400000"}],
    }
    res = client.post(f"{API}/contracts/{contract_id}/project", json=body, headers=key())
    assert res.status_code == 422 and res.json()["error"]["code"] == "terms_total_mismatch"
    assert (
        client.post(f"{API}/contracts/{contract_id}/project", json=body).status_code == 428
    )  # 재전송 키 필수


def test_project_creation_is_idempotent(client: TestClient) -> None:
    register(client)
    contract_id = confirmed_contract(client)
    body = {
        "name": "모노",
        "new_client_name": "모노 스튜디오",
        "job_type": "design",
        "contract_amount": "1000000",
        "payment_terms": [{"stage": "other", "label": "일시불", "amount": "1000000"}],
    }
    headers = key()
    first = client.post(f"{API}/contracts/{contract_id}/project", json=body, headers=headers)
    second = client.post(f"{API}/contracts/{contract_id}/project", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert client.get(f"{API}/projects").json()["counts"]["all"] == 1


# ---------------------------------------------------------------- 시연 시나리오: 잔금 발행 → 부분 입금
def test_demo_flow_issue_balance_and_partial_payment(client: TestClient) -> None:
    register(client)
    project, _ = project_from_contract(client)
    terms = term_ids(client, project["id"])

    # 선금 청구·입금
    deposit = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "디자인 선금")
    issued = client.post(f"{API}/invoices/{deposit['id']}/issue", json={}, headers=key())
    assert issued.status_code == 200, issued.text
    assert issued.json()["invoice_no"] == f"INV-{today().year}-001"
    res = client.post(
        f"{API}/invoices/{deposit['id']}/payments",
        json={"amount": "500000", "paid_on": today().isoformat()},
        headers=key(),
    )
    assert res.status_code == 201 and res.json()["payment_status"] == "paid"

    # 잔금 50만 원 발행
    balance = stage_invoice(client, project["id"], terms["잔금 50%"], "500000", "디자인 잔금")
    assert balance["status"] == "draft" and balance["invoice_no"] is None and balance["total"] == "500000"
    res = client.post(f"{API}/invoices/{balance['id']}/issue", json={}, headers=key())
    assert res.status_code == 200
    detail = res.json()
    assert detail["invoice_no"] == f"INV-{today().year}-002"
    snap = detail["snapshot"]
    assert snap["issuer"]["name"] == "김지윤" and snap["client"]["name"] == "모노 스튜디오"
    assert snap["items"][0]["payment_term"] == {"label": "잔금 50%", "requirement": "검수 완료 후"}
    assert snap["items"][0]["basis_note"] == "최종 납품 및 검수 확인"

    # 잔금 중 30만 원 입금 → 잔액 20만 원, 일부 입금
    res = client.post(
        f"{API}/invoices/{balance['id']}/payments",
        json={"amount": 300000, "paid_on": today().isoformat(), "memo": "잔금 일부"},
        headers=key(),
    )
    assert res.status_code == 201
    paid = res.json()
    assert (paid["paid_amount"], paid["balance"], paid["payment_status"]) == ("300000", "200000", "partial")

    # 같은 지급 단계 재청구 거절
    again = stage_invoice(client, project["id"], terms["잔금 50%"], "500000", "잔금 재청구")
    res = client.post(f"{API}/invoices/{again['id']}/issue", json={}, headers=key())
    assert res.status_code == 409 and res.json()["error"]["code"] == "over_billed"

    # 입금확인서 PDF
    payment_id = paid["payments"][0]["id"]
    receipt = client.get(f"{API}/payments/{payment_id}/receipt")
    assert receipt.status_code == 200 and receipt.content.startswith(b"%PDF-")
    assert receipt.headers["cache-control"] == "no-store"
    pdf = client.get(f"{API}/invoices/{balance['id']}/pdf", params={"download": True})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")

    # 목록 지표와 대시보드가 같은 값을 쓴다
    listing = client.get(f"{API}/invoices").json()
    assert listing["kpis"]["billed_this_month"] == "1000000"
    assert listing["kpis"]["paid_total"] == "800000"
    assert listing["kpis"]["outstanding_total"] == "200000"
    assert (
        listing["counts"]["draft"] == 1
        and listing["counts"]["partial"] == 1
        and listing["counts"]["paid"] == 1
    )
    dashboard = client.get(f"{API}/dashboard").json()
    assert dashboard["outstanding_total"] == "200000"


def test_issue_requires_due_date_and_confirmed_requirement(client: TestClient) -> None:
    register(client)
    project, _ = project_from_contract(client)
    terms = term_ids(client, project["id"])
    inv = stage_invoice(client, project["id"], terms["잔금 50%"], "500000", "잔금", confirm=False)
    res = client.post(f"{API}/invoices/{inv['id']}/issue", json={}, headers=key())
    assert res.status_code == 422 and res.json()["error"]["code"] == "requirement_unconfirmed"

    res = client.post(
        f"{API}/invoices",
        json={
            "project_id": project["id"],
            "title": "추가 작업",
            "items": [{"kind": "extra", "description": "배너 추가", "unit_price": "100000"}],
        },
    )
    res = client.post(f"{API}/invoices/{res.json()['id']}/issue", json={}, headers=key())
    assert res.status_code == 422 and res.json()["error"]["code"] == "due_date_required"


def test_server_recalculates_amounts(client: TestClient) -> None:
    register(client)
    project = client.post(
        f"{API}/projects", json={"name": "시간제", "new_client_name": "라이트", "contract_amount": 0}
    ).json()
    task = client.post(f"{API}/projects/{project['id']}/tasks", json={"title": "유지보수"}).json()

    # 시간이 기록되지 않은 작업은 시간제로 청구할 수 없다
    body = {
        "project_id": project["id"],
        "title": "11월 유지보수",
        "items": [{"kind": "hourly", "description": "유지보수", "unit_price": "1", "task_id": task["id"]}],
    }
    res = client.post(f"{API}/invoices", json=body)
    assert res.status_code == 422 and res.json()["error"]["code"] == "task_hours_missing"

    client.patch(f"{API}/tasks/{task['id']}", json={"hours": "2.5", "hourly_rate": 33333})
    res = client.post(
        f"{API}/invoices",
        json={**body, "tax_amount": "8333", "withholding_amount": "2750"},
    )
    assert res.status_code == 201
    inv = res.json()
    # 클라이언트가 보낸 단가(1)는 무시하고 확인된 시간 × 단가로 계산, 원 단위 반올림
    assert inv["items"][0]["quantity"] == "2.50" and inv["items"][0]["unit_price"] == "33333"
    assert inv["items"][0]["amount"] == "83333"  # 83332.5 → 83333
    assert (inv["subtotal"], inv["total"]) == ("83333", "88916")

    # 남의 지급 단계·작업은 연결할 수 없다
    res = client.post(
        f"{API}/invoices",
        json={
            "project_id": project["id"],
            "title": "x",
            "items": [
                {
                    "kind": "payment_stage",
                    "description": "x",
                    "unit_price": "1",
                    "payment_term_id": str(uuid.uuid4()),
                }
            ],
        },
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_payment_term"


def test_issued_invoice_is_immutable_and_cancel_reissue(client: TestClient) -> None:
    register(client)
    project, _ = project_from_contract(client)
    terms = term_ids(client, project["id"])
    inv = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "선금")
    body = {
        "project_id": project["id"],
        "title": "수정",
        "items": [{"kind": "extra", "description": "x", "unit_price": "1"}],
    }
    assert client.put(f"{API}/invoices/{inv['id']}", json=body).status_code == 200  # 초안은 수정 가능

    inv = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "선금")
    client.post(f"{API}/invoices/{inv['id']}/issue", json={}, headers=key())
    res = client.put(f"{API}/invoices/{inv['id']}", json=body)
    assert res.status_code == 409 and res.json()["error"]["code"] == "invoice_not_draft"
    assert client.delete(f"{API}/invoices/{inv['id']}").status_code == 409

    # 입금이 있으면 취소 불가 → 입금 취소 후 인보이스 취소 → 재발행 초안
    paid = client.post(
        f"{API}/invoices/{inv['id']}/payments",
        json={"amount": "100000", "paid_on": today().isoformat()},
        headers=key(),
    ).json()
    res = client.post(f"{API}/invoices/{inv['id']}/cancel", json={"reason": "금액 오류"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "invoice_has_payments"

    payment_id = paid["payments"][0]["id"]
    res = client.post(f"{API}/payments/{payment_id}/void", json={"reason": "잘못 입력"})
    assert res.status_code == 200 and res.json()["payments"][0]["voided_at"] is not None
    assert client.get(f"{API}/payments/{payment_id}/receipt").status_code == 409  # 취소된 입금은 확인서 무효

    res = client.post(f"{API}/invoices/{inv['id']}/cancel", json={"reason": "금액 오류"})
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    assert client.get(f"{API}/invoices/{inv['id']}/pdf").status_code == 200  # 취소본도 기록으로 열람 가능

    re = client.post(f"{API}/invoices/{inv['id']}/reissue")
    assert re.status_code == 201
    new = re.json()
    assert new["status"] == "draft" and new["replaces_invoice_id"] == inv["id"] and new["total"] == "500000"
    assert client.post(f"{API}/invoices/{inv['id']}/reissue").status_code == 409
    # 취소된 발행분은 한도에서 빠지므로 재발행할 수 있다
    assert client.post(f"{API}/invoices/{new['id']}/issue", json={}, headers=key()).status_code == 200


def test_payment_rules(client: TestClient) -> None:
    register(client)
    project, _ = project_from_contract(client)
    terms = term_ids(client, project["id"])
    inv = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "선금")

    res = client.post(
        f"{API}/invoices/{inv['id']}/payments",
        json={"amount": "1", "paid_on": today().isoformat()},
        headers=key(),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "invoice_not_issued"

    client.post(f"{API}/invoices/{inv['id']}/issue", json={}, headers=key())
    res = client.post(
        f"{API}/invoices/{inv['id']}/payments",
        json={"amount": "500001", "paid_on": today().isoformat()},
        headers=key(),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "overpayment"
    future = (today() + timedelta(days=1)).isoformat()
    res = client.post(
        f"{API}/invoices/{inv['id']}/payments", json={"amount": "1", "paid_on": future}, headers=key()
    )
    assert res.status_code == 422

    # 같은 재전송 키로 두 번 보내도 입금은 한 번만 기록된다
    headers = key()
    body = {"amount": "200000", "paid_on": today().isoformat()}
    first = client.post(f"{API}/invoices/{inv['id']}/payments", json=body, headers=headers)
    second = client.post(f"{API}/invoices/{inv['id']}/payments", json=body, headers=headers)
    assert first.status_code == second.status_code == 201
    assert len(client.get(f"{API}/invoices/{inv['id']}").json()["payments"]) == 1


def test_overdue_and_list_filters(client: TestClient) -> None:
    register(client)
    project, _ = project_from_contract(client)
    terms = term_ids(client, project["id"])
    inv = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "선금")
    client.post(f"{API}/invoices/{inv['id']}/issue", json={}, headers=key())
    # 지급 기한을 과거로 (시간이 흐른 상황)
    with get_engine().begin() as conn:
        conn.execute(text("ALTER TABLE invoices DISABLE TRIGGER invoices_guard_update"))
        conn.execute(
            text("UPDATE invoices SET due_date = current_date - 3 WHERE id = :id"), {"id": inv["id"]}
        )
        conn.execute(text("ALTER TABLE invoices ENABLE TRIGGER invoices_guard_update"))

    listing = client.get(f"{API}/invoices", params={"group": "overdue"}).json()
    assert [i["id"] for i in listing["items"]] == [inv["id"]]
    assert listing["items"][0]["is_overdue"] is True
    assert listing["kpis"]["overdue_count"] == 1 and listing["kpis"]["overdue_balance"] == "500000"
    assert client.get(f"{API}/invoices", params={"month": "2020-01"}).json()["items"] == []
    assert client.get(f"{API}/invoices", params={"month": "2020-13"}).status_code == 422

    # 미수 = 발행했고 잔액이 남은 것 (KPI 미수액과 같은 기준). 초안은 빠진다
    stage_invoice(client, project["id"], terms["잔금 50%"], "500000", "잔금")
    outstanding = client.get(f"{API}/invoices", params={"group": "outstanding"}).json()
    assert [i["id"] for i in outstanding["items"]] == [inv["id"]]
    assert outstanding["counts"]["outstanding"] == 1


def test_other_users_cannot_touch_invoices(client: TestClient) -> None:
    register(client, email="a@example.com")
    project, _ = project_from_contract(client)
    terms = term_ids(client, project["id"])
    inv = stage_invoice(client, project["id"], terms["선금 50%"], "500000", "선금")
    client.post(f"{API}/invoices/{inv['id']}/issue", json={}, headers=key())
    paid = client.post(
        f"{API}/invoices/{inv['id']}/payments",
        json={"amount": "1000", "paid_on": today().isoformat()},
        headers=key(),
    ).json()
    payment_id = paid["payments"][0]["id"]

    client.cookies.clear()
    register(client, email="b@example.com")
    assert client.get(f"{API}/invoices").json()["items"] == []
    for method, path in [
        ("GET", f"/invoices/{inv['id']}"),
        ("GET", f"/invoices/{inv['id']}/pdf"),
        ("GET", f"/payments/{payment_id}/receipt"),
        ("GET", f"/projects/{project['id']}/billing-candidates"),
    ]:
        assert client.request(method, f"{API}{path}").status_code == 404, path
    assert client.post(f"{API}/payments/{payment_id}/void", json={"reason": "x"}).status_code == 404
    res = client.post(
        f"{API}/invoices/{inv['id']}/payments",
        json={"amount": "1", "paid_on": today().isoformat()},
        headers=key(),
    )
    assert res.status_code == 404
    res = client.post(
        f"{API}/invoices",
        json={
            "project_id": project["id"],
            "title": "x",
            "items": [{"kind": "extra", "description": "x", "unit_price": "1"}],
        },
    )
    assert res.status_code == 404


def test_link_contract_to_existing_project(client: TestClient) -> None:
    """계약서 없이 만든 프로젝트에 나중에 올린 계약서를 연결한다"""
    register(client)
    manual = client.post(
        f"{API}/projects", json={"name": "프리더비스트", "new_client_name": "더비스트"}, headers=key()
    ).json()
    client.post(f"{API}/projects/{manual['id']}/tasks", json={"title": "기존 작업"})
    assert manual["has_contract"] is False

    contract_id = confirmed_contract(client)
    draft = client.post(f"{API}/contracts/{contract_id}/project-draft").json()
    body = {
        "project_id": manual["id"],
        "name": "프리더비스트",
        "job_type": draft["job_type"],
        "start_date": draft["start_date"],
        "due_date": draft["due_date"],
        "contract_amount": draft["contract_amount"],
        "payment_terms": [
            {k: t[k] for k in ("stage", "label", "ratio", "amount", "requirement")}
            for t in draft["payment_terms"]
        ],
        "tasks": [{"title": "계약 작업"}],
    }
    res = client.post(f"{API}/contracts/{contract_id}/project", json=body, headers=key())
    assert res.status_code == 200, res.text
    linked = res.json()
    assert linked["id"] == manual["id"] and linked["has_contract"] is True
    assert linked["contract_id"] == contract_id
    assert linked["client"]["name"] == "더비스트"  # 거래처는 그대로
    assert [t["label"] for t in linked["payment_terms"]] == ["선금 50%", "잔금 50%"]
    titles = [t["title"] for t in client.get(f"{API}/projects/{manual['id']}/tasks").json()]
    assert titles == ["기존 작업", "계약 작업"]
    assert client.get(f"{API}/contracts/{contract_id}").json()["project_id"] == manual["id"]
    assert client.get(f"{API}/projects").json()["counts"]["all"] == 1  # 새 프로젝트는 생기지 않는다

    # 이미 계약이 연결된 프로젝트에는 다른 계약을 붙일 수 없다
    other_id = confirmed_contract(client)
    res = client.post(f"{API}/contracts/{other_id}/project", json=body, headers=key())
    assert res.status_code == 409 and res.json()["error"]["code"] == "project_has_contract"

    # 남의 프로젝트는 존재를 드러내지 않는다
    client.cookies.clear()
    register(client, email="other@example.com")
    mine = confirmed_contract(client)
    res = client.post(f"{API}/contracts/{mine}/project", json=body, headers=key())
    assert res.status_code == 404


def _link_body(draft: dict, project_id: str, **extra: object) -> dict:
    return {
        "project_id": project_id,
        "name": draft["name"],
        "job_type": draft["job_type"],
        "start_date": draft["start_date"],
        "due_date": draft["due_date"],
        "contract_amount": draft["contract_amount"],
        "payment_terms": [
            {k: t[k] for k in ("stage", "label", "ratio", "amount", "requirement")}
            for t in draft["payment_terms"]
        ],
        **extra,
    }


def test_unlink_and_replace_contract_only_before_billing(client: TestClient) -> None:
    register(client)
    project, _ = project_from_contract(client)
    first_contract = project["contract_id"]

    # 청구 전에는 다른 계약서로 바꿀 수 있다 (수정 계약서를 새로 올린 경우)
    revised = confirmed_contract(client)
    draft = client.post(f"{API}/contracts/{revised}/project-draft").json()
    body = _link_body(draft, project["id"])
    res = client.post(f"{API}/contracts/{revised}/project", json=body, headers=key())
    assert res.status_code == 409 and res.json()["error"]["code"] == "project_has_contract"
    res = client.post(
        f"{API}/contracts/{revised}/project",
        json=_link_body(draft, project["id"], replace_contract=True),
        headers=key(),
    )
    assert res.status_code == 200, res.text
    assert res.json()["contract_id"] == revised
    # 예전 계약은 다시 쓸 수 있다
    assert client.get(f"{API}/contracts/{first_contract}").json()["project_id"] is None

    # 청구(초안 포함)가 생기면 해제·교체 모두 막는다
    terms = term_ids(client, project["id"])
    stage_invoice(client, project["id"], terms["선금 50%"], "500000", "선금")
    res = client.delete(f"{API}/projects/{project['id']}/contract")
    assert res.status_code == 409 and res.json()["error"]["code"] == "contract_has_billing"
    assert res.json()["error"]["details"]["invoice_count"] == 1
    draft = client.post(f"{API}/contracts/{first_contract}/project-draft").json()
    res = client.post(
        f"{API}/contracts/{first_contract}/project",
        json=_link_body(draft, project["id"], replace_contract=True),
        headers=key(),
    )
    assert res.status_code == 409 and res.json()["error"]["code"] == "contract_has_billing"


def test_unlink_contract(client: TestClient) -> None:
    register(client)
    project, _ = project_from_contract(client)
    res = client.delete(f"{API}/projects/{project['id']}/contract")
    assert res.status_code == 200, res.text
    detail = res.json()
    assert detail["has_contract"] is False and detail["payment_terms"] == []
    assert len(client.get(f"{API}/projects/{project['id']}/tasks").json()) == 2  # 작업은 남는다
    assert client.get(f"{API}/contracts/{project['contract_id']}").json()["project_id"] is None
    res = client.delete(f"{API}/projects/{project['id']}/contract")
    assert res.status_code == 409 and res.json()["error"]["code"] == "project_has_no_contract"
