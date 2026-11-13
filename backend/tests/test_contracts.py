import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.storage import get_storage
from app.db.models import StoredFile
from app.db.session import get_engine, get_sessionmaker
from app.extraction.extractor import text_quality
from app.extraction.fields import TextLine, find_fields
from app.extraction.ocr import TesseractOcr, parse_tesseract_tsv
from app.worker.__main__ import process
from app.worker.queue import LeaseLostError, claim_job, heartbeat, lock_own_job, reap_expired
from tests.conftest import register
from tests.pdfs import encrypted_pdf, image_pdf, text_pdf

API = "/api/v1"

CONTRACT_LINES = [
    "Design Service Agreement",
    "Article 1. Scope: brand logo and guide",
    "Article 2. Total fee is paid in two parts",
]


def upload(client: TestClient, data: bytes, name: str = "brand.pdf", **form: str):
    return client.post(f"{API}/contracts", files={"file": (name, data, "application/pdf")}, data=form)


def run_worker_once() -> None:
    with get_sessionmaker()() as db:
        job = claim_job(db, ["extract"], get_settings().job_lease_seconds)
    assert job is not None, "no queued job"
    process(job)


# ---------------------------------------------------------------- 단위: 항목 후보·품질·OCR 결과 해석
def test_find_fields_in_korean_contract() -> None:
    lines = [
        TextLine("p1-b000", "디자인 용역 계약서"),
        TextLine("p1-b004", "총 계약 금액은 1,000,000원으로 한다."),
        TextLine("p1-b005", "계약 체결 후 선금 50%, 검수 완료 후 잔금 50%를 지급한다."),
        TextLine("p1-b007", "최종 납품일은 2026년 11월 20일로 한다."),
        TextLine("p2-b001", "무상 수정은 2회까지 제공한다."),
    ]
    found = {f.key: f for f in find_fields(lines)}
    assert found["contract_amount"].value == "1000000"
    assert found["contract_amount"].block_key == "p1-b004"
    # 지급 요건(계약 체결 후, 검수 완료 후)을 함께 남긴다: 청구할 때 충족 확인의 근거
    assert found["payment_terms"].value == "계약 체결 후 선금 50% · 검수 완료 후 잔금 50%"
    assert found["final_due_date"].value == "2026-11-20"
    assert found["revision_count"].value == "2회"


def test_find_fields_in_numbered_clause_contract() -> None:
    """조항 번호가 붙고, 요건이 단계 뒤에 오고, 단계가 여러 줄에 나뉜 계약서 (실제 사용자 문서 형식)."""
    lines = [
        TextLine("p1-b012", "제3조 계약 기간과 납품"),
        TextLine("p1-b013", "1. 계약 기간은 2026년 11월 16일부터 2026년 12월 4일까지로 한다."),
        TextLine("p1-b014", "2. 최초 시안은 2026년 11월 23일까지 전달한다."),
        TextLine("p1-b015", "3. 최종 산출물은 2026년 12월 4일까지 발주자가 지정한 이메일로 전달한다."),
        TextLine("p1-b017", "제4조 계약 금액과 지급 조건"),
        TextLine("p1-b018", "1. 총 계약 금액은 금 일백만원정(1,000,000원)으로 한다."),
        TextLine(
            "p1-b019",
            "2. 선금은 총 계약 금액의 50%인 500,000원으로 하며, 계약 체결일로부터 3영업일 이내에 지급한다.",
        ),
        TextLine(
            "p1-b020",
            "3. 잔금은 총 계약 금액의 50%인 500,000원으로 하며, "
            "최종 산출물의 검수 완료일로부터 7일 이내에 지급한",
        ),
        TextLine("p2-b011", "5. 발주자의 요청에 따라 필요한 디자인 수정에 협조한다."),
    ]
    found = {f.key: f for f in find_fields(lines)}
    assert found["contract_amount"].value == "1000000"
    # 최초 시안 날짜가 아니라 최종 산출물 날짜
    assert (found["final_due_date"].value, found["final_due_date"].block_key) == ("2026-12-04", "p1-b015")
    assert found["payment_terms"].value == (
        "계약 체결일로부터 3영업일 이내 선금 50% · 최종 산출물의 검수 완료일로부터 7일 이내 잔금 50%"
    )
    assert found["payment_terms"].block_key == "p1-b019"
    assert "revision_count" not in found  # 횟수가 없는 문장에서 만들어 내지 않는다

    # 납품 문장이 없으면 계약 기간의 끝 날짜
    period_only = [lines[1], lines[2]]
    assert {f.key: f.value for f in find_fields(period_only)}["final_due_date"] == "2026-12-04"


def test_find_fields_tolerates_ocr_spacing_but_not_ambiguous_numbers() -> None:
    lines = [
        TextLine("p1-b001", "계 약 금액 은 1.000,000 원으로 한다"),  # 구분자가 섞인 오인식 의심 값
        TextLine("p1-b002", "선 금 50% ㆍ 잔 금 50%"),
        TextLine("p1-b003", "최종 납 품일 : 2026. 11. 20"),
    ]
    found = {f.key: f.value for f in find_fields(lines)}
    assert "contract_amount" not in found
    assert found["payment_terms"] == "선금 50% · 잔금 50%"
    assert found["final_due_date"] == "2026-11-20"


def test_find_fields_reports_nothing_it_cannot_see() -> None:
    lines = [
        TextLine("p1-b000", "세부 사용 범위는 상호 협의에 따른다."),
        TextLine("p1-b001", "납품일 2026년 13월 40일"),
    ]
    assert find_fields(lines) == []  # 없는 값·잘못된 날짜를 만들어 내지 않는다


def test_text_quality() -> None:
    assert text_quality("총 계약 금액은 1,000,000원") == 1.0
    assert text_quality("(cid:12)(cid:34)(cid:56) 금액") < 0.5
    assert text_quality("   ") == 0.0


def test_parse_tesseract_tsv_groups_words_into_lines() -> None:
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        "5\t1\t1\t1\t1\t1\t100\t50\t80\t30\t96\t계약",
        "5\t1\t1\t1\t1\t2\t190\t52\t60\t28\t90\t금액",
        "5\t1\t1\t1\t2\t1\t100\t100\t200\t30\t-1\t ",
        "5\t1\t1\t1\t3\t1\t100\t150\t120\t30\t80\t1,000,000원",
    ]
    lines = parse_tesseract_tsv("\n".join([header, *rows]))
    assert [ln.text for ln in lines] == ["계약 금액", "1,000,000원"]
    assert (lines[0].x0, lines[0].x1) == (100, 250)
    assert lines[0].confidence == pytest.approx(0.93)


# ---------------------------------------------------------------- 업로드 검사
def test_upload_rejects_non_pdf_encrypted_and_damaged(client: TestClient) -> None:
    register(client)
    res = upload(client, b"MZ\x90\x00 this is an exe renamed to pdf", name="contract.pdf")
    assert res.status_code == 422 and res.json()["error"]["code"] == "not_pdf"

    res = upload(client, encrypted_pdf())
    assert res.status_code == 422 and res.json()["error"]["code"] == "encrypted_pdf"

    res = upload(client, b"%PDF-1.4\n garbage without objects")
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid_pdf"

    settings = get_settings()
    original = settings.max_pdf_pages
    settings.max_pdf_pages = 1
    try:
        res = upload(client, text_pdf([["a"], ["b"]]))
        assert res.status_code == 422 and res.json()["error"]["code"] == "too_many_pages"
    finally:
        settings.max_pdf_pages = original

    # 거절된 파일은 저장소에도 DB에도 남지 않는다
    assert client.get(f"{API}/contracts").json()["counts"]["all"] == 0
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM files")).scalar() == 0


def test_upload_rejects_too_large(client: TestClient) -> None:
    register(client)
    settings = get_settings()
    original = settings.max_upload_mb
    settings.max_upload_mb = 0
    try:
        res = upload(client, text_pdf([["hello"]]))
        assert res.status_code == 413 and res.json()["error"]["code"] == "file_too_large"
    finally:
        settings.max_upload_mb = original


# ---------------------------------------------------------------- 업로드 → 추출 → 확인
def test_upload_extract_and_review_flow(client: TestClient) -> None:
    register(client)
    res = upload(
        client,
        text_pdf([CONTRACT_LINES, ["Article 3. Delivery and inspection"]]),
        title="브랜드 디자인 용역 계약서",
    )
    assert res.status_code == 202, res.text
    body = res.json()
    contract_id, job_id = body["contract"]["id"], body["job"]["id"]
    assert body["contract"]["status"] == "uploaded"
    assert body["contract"]["page_count"] == 2
    assert body["job"]["status"] == "queued"
    assert client.get(f"{API}/contracts").json()["counts"]["processing"] == 1

    run_worker_once()

    detail = client.get(f"{API}/contracts/{contract_id}").json()
    assert detail["status"] == "needs_review"
    assert detail["job"]["status"] == "succeeded"
    assert [(p["page_no"], p["method"], p["needs_review"]) for p in detail["pages"]] == [
        (1, "text", False),
        (2, "text", False),
    ]
    # 영문 계약서라 핵심 항목 후보는 없다: 미확정으로 남는다
    assert {f["key"]: f["extracted_value"] for f in detail["fields"]} == {
        "contract_amount": None,
        "final_due_date": None,
        "payment_terms": None,
        "revision_count": None,
    }
    assert client.get(f"{API}/jobs/{job_id}").json()["status"] == "succeeded"

    extracted = client.get(f"{API}/contracts/{contract_id}/text").json()
    page1 = extracted["pages"][0]
    assert [b["text"] for b in page1["blocks"]] == CONTRACT_LINES
    assert page1["blocks"][0]["key"] == "p1-b000"
    assert page1["blocks"][0]["bbox"]["page_width"] == 612.0

    original = client.get(f"{API}/contracts/{contract_id}/file", params={"download": True})
    assert original.status_code == 200
    assert original.headers["cache-control"] == "no-store"
    assert original.headers["content-disposition"].startswith("attachment;")
    assert original.content.startswith(b"%PDF-")

    # 필수 항목 없이 확정하면 거절
    res = client.patch(f"{API}/contracts/{contract_id}/fields", json={"values": {}, "confirm": True})
    assert res.status_code == 422 and res.json()["error"]["details"]["fields"] == [
        "contract_amount",
        "final_due_date",
        "payment_terms",
    ]
    res = client.patch(
        f"{API}/contracts/{contract_id}/fields", json={"values": {"contract_amount": "1,000,000"}}
    )
    assert res.status_code == 422  # 숫자만

    res = client.patch(
        f"{API}/contracts/{contract_id}/fields",
        json={
            "values": {
                "contract_amount": "1000000",
                "final_due_date": "2026-11-20",
                "payment_terms": "선금 50% · 잔금 50%",
            },
            "confirm": True,
        },
    )
    assert res.status_code == 200, res.text
    confirmed = res.json()
    assert confirmed["status"] == "ready"
    by_key = {f["key"]: f for f in confirmed["fields"]}
    assert by_key["contract_amount"]["confirmed_value"] == "1000000"
    assert by_key["contract_amount"]["extracted_value"] is None  # 원본 추출값은 보존
    assert (
        by_key["revision_count"]["status"] == "confirmed"
        and by_key["revision_count"]["confirmed_value"] is None
    )

    # 확정 뒤 값을 바꾸면 다시 확인 필요
    res = client.patch(
        f"{API}/contracts/{contract_id}/fields", json={"values": {"contract_amount": "900000"}}
    )
    assert res.json()["status"] == "needs_review"
    assert {f["key"]: f["status"] for f in res.json()["fields"]}["contract_amount"] == "unconfirmed"


def test_other_users_cannot_access_contracts(client: TestClient) -> None:
    register(client, email="a@example.com")
    body = upload(client, text_pdf([CONTRACT_LINES])).json()
    contract_id, job_id = body["contract"]["id"], body["job"]["id"]
    run_worker_once()

    client.cookies.clear()
    register(client, email="b@example.com")
    assert client.get(f"{API}/contracts").json()["items"] == []
    for path in ("", "/file", "/text"):
        assert client.get(f"{API}/contracts/{contract_id}{path}").status_code == 404
    assert client.patch(f"{API}/contracts/{contract_id}/fields", json={"values": {}}).status_code == 404
    assert client.delete(f"{API}/contracts/{contract_id}").status_code == 404
    assert client.get(f"{API}/jobs/{job_id}").status_code == 404
    assert client.post(f"{API}/jobs/{job_id}/cancel").status_code == 404


def test_list_search_and_groups(client: TestClient) -> None:
    register(client)
    client_id = client.post(f"{API}/clients", json={"name": "모노 스튜디오"}).json()["id"]
    upload(client, text_pdf([CONTRACT_LINES]), title="브랜드 디자인 용역 계약서", client_id=client_id)
    upload(client, text_pdf([CONTRACT_LINES]), title="웹사이트 리뉴얼 계약서")
    run_worker_once()

    res = client.get(f"{API}/contracts").json()
    assert res["counts"] == {
        "all": 2,
        "processing": 1,
        "needs_review": 1,
        "ready": 0,
        "analyzed": 0,
        "failed": 0,
    }
    assert [c["title"] for c in client.get(f"{API}/contracts", params={"q": "모노"}).json()["items"]] == [
        "브랜드 디자인 용역 계약서"
    ]
    assert len(client.get(f"{API}/contracts", params={"q": "100%_"}).json()["items"]) == 0
    group = client.get(f"{API}/contracts", params={"group": "processing"}).json()["items"]
    assert [c["status"] for c in group] == ["uploaded"]


# ---------------------------------------------------------------- 스캔 PDF·OCR
def test_scanned_pdf_without_ocr_fails_and_can_retry(client: TestClient) -> None:
    register(client)
    contract_id = upload(client, text_pdf([[]])).json()["contract"]["id"]
    run_worker_once()  # 테스트 기본값: OCR 끔

    detail = client.get(f"{API}/contracts/{contract_id}").json()
    assert detail["status"] == "failed"
    assert detail["failure_reason"] == "no_text_ocr_disabled"
    assert detail["job"]["status"] == "failed"

    res = client.post(f"{API}/contracts/{contract_id}/extract")
    assert res.status_code == 202
    assert res.json()["contract"]["status"] == "uploaded"
    assert client.post(f"{API}/contracts/{contract_id}/extract").status_code == 409


def test_ocr_reads_scanned_page(client: TestClient) -> None:
    register(client)
    contract_id = upload(client, image_pdf(["TOTAL FEE 1,000,000 KRW", "DELIVERY 2026-11-20"])).json()[
        "contract"
    ]["id"]

    settings = get_settings()
    original = settings.ocr_engine
    settings.ocr_engine = "tesseract"
    try:
        run_worker_once()
    finally:
        settings.ocr_engine = original

    detail = client.get(f"{API}/contracts/{contract_id}").json()
    assert detail["status"] == "needs_review"
    assert detail["pages"][0]["method"] == "ocr"
    assert detail["pages"][0]["needs_review"] is True  # OCR 페이지는 항상 원문 비교
    joined = " ".join(
        b["text"] for b in client.get(f"{API}/contracts/{contract_id}/text").json()["pages"][0]["blocks"]
    )
    assert "1,000,000" in joined
    assert isinstance(TesseractOcr("kor+eng"), TesseractOcr)


# ---------------------------------------------------------------- 작업 큐: 점유 만료·늦은 결과·취소
def test_expired_lease_is_reclaimed_and_late_worker_is_rejected(client: TestClient) -> None:
    register(client)
    upload(client, text_pdf([CONTRACT_LINES]))
    maker = get_sessionmaker()
    with maker() as db:
        stale = claim_job(db, ["extract"], 60)
        assert stale is not None
        db.execute(
            text("UPDATE analysis_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id"),
            {"id": stale.id},
        )
        db.commit()
        assert reap_expired(db) == 0  # 시도 횟수가 남아 다시 대기열로 (버전 실패 아님)
        fresh = claim_job(db, ["extract"], 60)
        assert fresh is not None and fresh.id == stale.id and fresh.run_id != stale.run_id
        assert fresh.attempts == 2

        # 앞선 작업자는 점유를 잃었으므로 갱신·저장 모두 거절된다
        with pytest.raises(LeaseLostError):
            heartbeat(db, stale, "extracting", 60)
        with pytest.raises(LeaseLostError):
            lock_own_job(db, stale)
        db.rollback()

    process(fresh)
    with get_engine().connect() as conn:
        assert (
            conn.execute(text("SELECT status FROM analysis_jobs WHERE id = :id"), {"id": fresh.id}).scalar()
            == "succeeded"
        )


def test_lease_expiry_after_last_attempt_fails_version(client: TestClient) -> None:
    register(client)
    contract_id = upload(client, text_pdf([CONTRACT_LINES])).json()["contract"]["id"]
    with get_sessionmaker()() as db:
        job = claim_job(db, ["extract"], 60)
        assert job is not None
        db.execute(
            text(
                "UPDATE analysis_jobs SET attempts = max_attempts, "
                "lease_expires_at = now() - interval '1 s' WHERE id = :id"
            ),
            {"id": job.id},
        )
        db.commit()
        assert reap_expired(db) == 1
    detail = client.get(f"{API}/contracts/{contract_id}").json()
    assert detail["status"] == "failed" and detail["failure_reason"] == "worker_stopped"


def test_cancel_queued_and_running_jobs(client: TestClient) -> None:
    register(client)
    body = upload(client, text_pdf([CONTRACT_LINES])).json()
    res = client.post(f"{API}/jobs/{body['job']['id']}/cancel")
    assert res.status_code == 200 and res.json()["status"] == "cancelled"
    detail = client.get(f"{API}/contracts/{body['contract']['id']}").json()
    assert detail["status"] == "failed" and detail["failure_reason"] == "cancelled"
    assert client.post(f"{API}/jobs/{body['job']['id']}/cancel").status_code == 409

    # 실행 중 취소: 작업자가 다음 페이지에서 멈춘다
    body = upload(client, text_pdf([CONTRACT_LINES, CONTRACT_LINES])).json()
    with get_sessionmaker()() as db:
        job = claim_job(db, ["extract"], 60)
    assert job is not None
    res = client.post(f"{API}/jobs/{job.id}/cancel")
    assert res.json()["status"] == "running" and res.json()["cancel_requested"] is True
    process(job)
    assert client.get(f"{API}/jobs/{job.id}").json()["status"] == "cancelled"
    assert client.get(f"{API}/contracts/{body['contract']['id']}").json()["failure_reason"] == "cancelled"


def test_delete_contract_removes_original(client: TestClient) -> None:
    register(client)
    body = upload(client, text_pdf([CONTRACT_LINES])).json()
    contract_id = body["contract"]["id"]

    res = client.delete(f"{API}/contracts/{contract_id}")
    assert res.status_code == 409 and res.json()["error"]["code"] == "contract_busy"

    run_worker_once()
    with get_sessionmaker()() as db:
        key = db.execute(text("SELECT object_key FROM files")).scalar_one()
        assert db.query(StoredFile).count() == 1
    storage = get_storage()
    assert storage.open(key).read(5) == b"%PDF-"

    assert client.delete(f"{API}/contracts/{contract_id}").status_code == 204
    assert client.get(f"{API}/contracts/{contract_id}").status_code == 404
    with pytest.raises(FileNotFoundError):
        storage.open(key)
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM files")).scalar() == 0
        assert conn.execute(text("SELECT count(*) FROM analysis_jobs")).scalar() == 0


def test_unknown_contract_is_404(client: TestClient) -> None:
    register(client)
    assert client.get(f"{API}/contracts/{uuid.uuid4()}").status_code == 404


def test_deleting_user_with_confirmed_contract_succeeds(client: TestClient) -> None:
    """TRUNCATE는 FK 동작을 건너뛰므로, 실제 DELETE로 사용자 삭제 경로를 검증한다."""
    register(client)
    contract_id = upload(client, text_pdf([CONTRACT_LINES])).json()["contract"]["id"]
    run_worker_once()
    res = client.patch(
        f"{API}/contracts/{contract_id}/fields",
        json={
            "values": {
                "contract_amount": "1000000",
                "final_due_date": "2026-11-20",
                "payment_terms": "선금 50%",
            },
            "confirm": True,
        },
    )
    assert res.status_code == 200
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM users WHERE email = 'jiyoon@example.com'"))
        assert conn.execute(text("SELECT count(*) FROM contract_fields")).scalar() == 0


def test_referenced_rows_still_cannot_be_deleted_alone(client: TestClient) -> None:
    """NO ACTION으로 바꿔도 참조 중인 원본 파일을 단독으로 지울 수는 없다."""
    register(client)
    upload(client, text_pdf([CONTRACT_LINES]))
    with (
        pytest.raises(Exception, match="contract_versions_file_id_owner_id_fkey"),
        get_engine().begin() as conn,
    ):
        conn.execute(text("DELETE FROM files"))
