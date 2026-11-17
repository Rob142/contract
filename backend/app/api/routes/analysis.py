import hashlib
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.llm import (
    FakeProvider,
    LiteLlmProvider,
    LlmOutputError,
    LlmProvider,
    LlmTransientError,
    LlmUnavailableError,
    _normalize_commercial_model,
    _normalize_local_model,
    get_provider,
    provider_status,
)
from app.analysis.review import JOB_LABELS, PROMPT_VERSION
from app.analysis.rules import RULES_VERSION, rules_for
from app.api.deps import get_current_user
from app.core.audit import record_audit
from app.core.clock import now_utc
from app.core.errors import AppError, conflict
from app.db.models import AnalysisJob, AnalysisResult, Contract, ContractVersion, User
from app.db.session import get_db
from app.schemas.analysis import (
    AnalysisCounts,
    AnalysisOut,
    AnalysisView,
    AnalyzeIn,
    AnalyzeOut,
    EvidenceOut,
    LlmStatus,
    LlmTestIn,
    LlmTestOut,
    ResultOut,
    RevisionPromptIn,
    RevisionPromptOut,
)
from app.services.contracts import get_owned_contract, job_out, latest_text_version

router = APIRouter(tags=["analysis"])

LEVEL_ORDER = {"caution": 0, "needs_check": 1, "confirmed": 2}
STATUS_LABELS = {"found": "있음", "not_found": "계약서에 없음(미발견)", "unclear": "모호함(불명확)"}


@router.get("/llm/status", response_model=LlmStatus)
def llm_status(user: User = Depends(get_current_user)) -> LlmStatus:
    return LlmStatus.model_validate(provider_status(user))


@router.post("/llm/test", response_model=LlmTestOut)
def test_llm_connection(body: LlmTestIn, user: User = Depends(get_current_user)) -> LlmTestOut:
    """설정한(또는 입력 중인) LLM 모델에 짧은 JSON 응답을 요청해 연결을 확인한다."""
    try:
        provider: LlmProvider
        if body.model is not None or body.api_key is not None or body.api_base is not None:
            if body.mode == "local":
                raw_model = (body.model or "").strip() or user.local_llm_model
                api_base = (body.api_base or "").strip() or user.local_llm_api_base
                local_key = (body.api_key or "").strip() or user.local_llm_api_key or "local"
                if not raw_model:
                    raise LlmUnavailableError("local_llm_not_configured", "로컬 모델명을 입력해 주세요.")
                if raw_model == "fake":
                    provider = FakeProvider()
                else:
                    norm_model, prov = _normalize_local_model(raw_model, api_base)
                    provider = LiteLlmProvider(
                        model_id=norm_model,
                        api_key=local_key,
                        api_base=api_base,
                        timeout_seconds=15,
                        provider_name=prov,
                    )
            else:
                raw_model = (body.model or "").strip() or user.commercial_llm_model
                api_base = (body.api_base or "").strip() or user.commercial_llm_api_base
                comm_key = (body.api_key or "").strip() or user.commercial_llm_api_key
                if raw_model == "fake":
                    provider = FakeProvider()
                elif raw_model or comm_key or api_base:
                    norm_model, prov = _normalize_commercial_model(raw_model or "gemini/gemini-2.5-flash")
                    if not comm_key:
                        raise LlmUnavailableError("llm_not_configured", "API 키를 입력해 주세요.")
                    provider = LiteLlmProvider(
                        model_id=norm_model,
                        api_key=comm_key,
                        api_base=api_base,
                        timeout_seconds=15,
                        provider_name=prov,
                    )
                else:
                    provider = get_provider("commercial", user)
        else:
            provider = get_provider(body.mode, user)

        if isinstance(provider, FakeProvider):
            return LlmTestOut(
                ok=True,
                provider=provider.provider,
                model_id=provider.model_id,
                message="시연용 가짜 모델이 정상 동작해요.",
            )

        res = provider.generate_json(
            'You are a connection test assistant. Respond with JSON {"status": "ok"}.',
            "ping",
            {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]},
            max_output_tokens=64,
        )
        return LlmTestOut(
            ok=True,
            provider=provider.provider,
            model_id=res.model_id,
            message=f"연결에 성공했어요 ({res.model_id}).",
        )
    except LlmUnavailableError as exc:
        raise conflict(exc.code, str(exc)) from exc
    except (LlmTransientError, LlmOutputError) as exc:
        raise conflict(exc.code, str(exc)) from exc


def _analysis_jobs(db: Session, version_id: UUID) -> list[AnalysisJob]:
    return list(
        db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.contract_version_id == version_id, AnalysisJob.kind == "analyze")
            .order_by(AnalysisJob.created_at.desc())
        ).scalars()
    )


@router.post("/contracts/{contract_id}/analyze", status_code=202, response_model=AnalyzeOut)
def request_analysis(
    contract_id: UUID, body: AnalyzeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> JSONResponse:
    """확인된 텍스트 버전으로 분석 작업을 등록한다 (202 + 작업 ID). 실제 호출은 작업자가 한다."""
    contract, version, _ = get_owned_contract(db, user.id, contract_id)
    db.execute(select(ContractVersion).where(ContractVersion.id == version.id).with_for_update())
    if any(j.status in ("queued", "running") for j in _analysis_jobs(db, version.id)):
        raise conflict("analysis_running", "an analysis is already running for this contract")
    if version.status not in ("ready", "analyzed"):
        raise conflict("contract_not_confirmed", "confirm the contract fields before analysis")
    if body.llm_mode == "commercial" and not body.consent_external:
        raise AppError(
            422, "consent_required", "consent to sending the contract text to the external model is required"
        )
    try:
        provider = get_provider(body.llm_mode, user)
    except LlmUnavailableError as exc:
        raise conflict(exc.code, str(exc)) from exc

    text_version = latest_text_version(db, version.id)
    if text_version is None:
        raise conflict("contract_not_confirmed", "the contract has no extracted text")
    job_type = body.job_type or contract.job_type
    # 같은 소유자·텍스트 버전·직업군·규칙·프롬프트·모델이면 이전 결과를 다시 쓴다 (설계서 5장)
    reuse_key = hashlib.sha256(
        "|".join(
            [
                str(user.id),
                str(text_version.id),
                job_type,
                RULES_VERSION,
                PROMPT_VERSION,
                provider.provider,
                provider.model_id,
            ]
        ).encode()
    ).hexdigest()

    if not body.force:
        previous = db.execute(
            select(AnalysisJob)
            .where(
                AnalysisJob.owner_id == user.id,
                AnalysisJob.reuse_key == reuse_key,
                AnalysisJob.status == "succeeded",
                AnalysisJob.contract_version_id == version.id,
            )
            .order_by(AnalysisJob.finished_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if previous is not None:
            return JSONResponse(
                AnalyzeOut(job=job_out(previous), reused=True).model_dump(mode="json"), status_code=200
            )

    job = AnalysisJob(
        owner_id=user.id,
        contract_version_id=version.id,
        text_version_id=text_version.id,
        kind="analyze",
        job_type=job_type,
        llm_mode=body.llm_mode,
        model_config_={"provider": provider.provider, "model": provider.model_id},
        rules_version=RULES_VERSION,
        prompt_version=PROMPT_VERSION,
        input={"previous_status": version.status},
        reuse_key=reuse_key,
        external_send_consented_at=now_utc() if body.llm_mode == "commercial" else None,
    )
    db.add(job)
    version.status = "analyzing"
    record_audit(
        db,
        actor_id=user.id,
        action="contract.analyze",
        target_type="contract_version",
        target_id=version.id,
        llm_mode=body.llm_mode,
        provider=provider.provider,
        model=provider.model_id,
        external_send_consented=body.consent_external,
    )
    db.commit()
    db.refresh(job)
    return JSONResponse(AnalyzeOut(job=job_out(job), reused=False).model_dump(mode="json"), status_code=202)


def _latest_succeeded(db: Session, version_id: UUID) -> AnalysisJob | None:
    return next((j for j in _analysis_jobs(db, version_id) if j.status == "succeeded"), None)


def _result_out(r: AnalysisResult, job_type: str) -> ResultOut:
    rules = {rule.id: rule for rule in rules_for(job_type)}
    rule = rules.get(r.rule_id)
    return ResultOut(
        id=r.id,
        rule_id=r.rule_id,
        rule_title=rule.title if rule else r.rule_id,
        importance=rule.importance if rule else "medium",
        status=r.status,  # type: ignore[arg-type]
        review_level=r.review_level,  # type: ignore[arg-type]
        risk_level=(r.raw_response or {}).get("risk_level"),
        title=r.title,
        explanation=r.explanation,
        user_action=r.user_action,
        suggestion=r.suggestion,
        evidence=[EvidenceOut(**e) for e in r.evidence],
        validation_status=r.validation_status,  # type: ignore[arg-type]
    )


@router.get("/contracts/{contract_id}/analysis", response_model=AnalysisView)
def read_analysis(
    contract_id: UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> AnalysisView:
    _, version, _ = get_owned_contract(db, user.id, contract_id)
    jobs = _analysis_jobs(db, version.id)
    latest = jobs[0] if jobs else None
    done = _latest_succeeded(db, version.id)
    if done is None:
        return AnalysisView(analysis=None, latest_job=job_out(latest) if latest else None)

    job_type = done.job_type or "design"
    rule_order = {rule.id: i for i, rule in enumerate(rules_for(job_type))}
    rows = list(db.execute(select(AnalysisResult).where(AnalysisResult.job_id == done.id)).scalars())
    rows.sort(key=lambda r: (LEVEL_ORDER.get(r.review_level, 9), rule_order.get(r.rule_id, 99)))
    results = [_result_out(r, job_type) for r in rows]
    config = done.model_config_ or {}
    return AnalysisView(
        analysis=AnalysisOut(
            job_id=done.id,
            analyzed_at=done.finished_at,
            llm_mode=done.llm_mode,
            provider=config.get("provider"),
            model_id=config.get("model_id") or config.get("model"),
            job_type=job_type,  # type: ignore[arg-type]
            rules_version=done.rules_version,
            prompt_version=done.prompt_version,
            counts=AnalysisCounts(
                total=len(results),
                caution=sum(r.review_level == "caution" for r in results),
                needs_check=sum(r.review_level == "needs_check" for r in results),
                confirmed=sum(r.review_level == "confirmed" for r in results),
            ),
            results=results,
        ),
        latest_job=job_out(latest) if latest else None,
    )


@router.post("/contracts/{contract_id}/revision-prompt", response_model=RevisionPromptOut)
def revision_prompt(
    contract_id: UUID,
    body: RevisionPromptIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RevisionPromptOut:
    """선택한 검토 항목으로 수정 요청 프롬프트를 만든다 (설계서 4장).

    문제·기존 조항과 근거·수정 방향·미확정 사항을 묶는다. 서버에서 문장을 조립할 뿐 외부로 보내지 않고,
    원본 계약서는 바꾸지 않는다. 사용자가 복사해 원하는 도구에 붙여 쓴다.
    """
    contract, version, _ = get_owned_contract(db, user.id, contract_id)
    done = _latest_succeeded(db, version.id)
    if done is None:
        raise conflict("analysis_not_found", "analyze the contract first")
    wanted = set(body.result_ids)
    rows = [
        r
        for r in db.execute(select(AnalysisResult).where(AnalysisResult.job_id == done.id)).scalars()
        if r.id in wanted
    ]
    if len(rows) != len(wanted):
        raise AppError(422, "invalid_result", "some results do not belong to this analysis")
    job_type = done.job_type or "design"
    rule_order = {rule.id: i for i, rule in enumerate(rules_for(job_type))}
    rows.sort(key=lambda r: rule_order.get(r.rule_id, 99))

    contract_row = db.get(Contract, contract.id)
    title = contract_row.title if contract_row else "계약서"
    lines = [
        f"{title}({JOB_LABELS.get(job_type, job_type)} 용역)의 아래 조항을 수정하려고 합니다.",
        "원본 계약서 문장은 그대로 두고, 항목마다 ① 수정 조항 초안과 "
        "② 거래처에 보낼 짧은 협의 문구를 제안해 주세요.",
        "",
    ]
    for i, r in enumerate(rows, start=1):
        lines.append(f"{i}. {r.title}")
        lines.append(f"- 현재 상태: {STATUS_LABELS.get(r.status, r.status)}")
        for ev in r.evidence:
            if ev.get("valid"):
                lines.append(f'- 기존 조항({ev["page_no"]}쪽): "{ev["quote"]}"')
        if r.suggestion:
            lines.append(f"- 원하는 수정 방향: {r.suggestion}")
        if r.user_action:
            lines.append(f"- 확인이 필요한 점: {r.user_action}")
        lines.append("")
    lines.append("확정되지 않은 금액·기간·횟수는 임의로 채우지 말고 [협의 필요]로 남겨 주세요.")
    return RevisionPromptOut(prompt="\n".join(lines), result_count=len(rows))
