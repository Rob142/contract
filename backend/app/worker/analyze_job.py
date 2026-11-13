"""분석 작업: 확인된 텍스트 버전 → 규칙별 LLM 분석 → 근거 검증 → 결과 저장 (설계서 4·5장)."""

import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.llm import get_provider
from app.analysis.review import PROMPT_VERSION, Block, run_review
from app.analysis.rules import RULES_VERSION, rules_for
from app.core.config import Settings
from app.db.models import AnalysisJob, AnalysisResult, ContractTextBlock, ContractVersion, User
from app.worker.extract_job import JobTimeoutError, PermanentJobError
from app.worker.queue import ClaimedJob, finish_job, heartbeat, lock_own_job

logger = logging.getLogger(__name__)


def run_analyze(db: Session, job: ClaimedJob, settings: Settings) -> None:
    row = db.get(AnalysisJob, job.id)
    version = db.get(ContractVersion, job.contract_version_id)
    if row is None or version is None or row.text_version_id is None:
        raise PermanentJobError("contract_deleted", "the contract or its text was deleted")

    owner = db.get(User, row.owner_id)
    mode = row.llm_mode or "commercial"
    try:
        provider = get_provider(mode, owner)  # type: ignore[arg-type]
    except TypeError:
        provider = get_provider(mode)  # type: ignore[arg-type]
    rules = rules_for(row.job_type or "design")
    blocks = [
        Block(b.block_key, b.page_no, b.text)
        for b in db.execute(
            select(ContractTextBlock)
            .where(ContractTextBlock.text_version_id == row.text_version_id)
            .order_by(ContractTextBlock.page_no, ContractTextBlock.position)
        ).scalars()
    ]
    if not blocks:
        raise PermanentJobError("no_text", "the confirmed text is empty")

    started = time.monotonic()

    def on_part(part: int, parts: int) -> None:
        if time.monotonic() - started > settings.job_timeout_seconds:
            raise JobTimeoutError("timeout", "analysis took too long")
        heartbeat(db, job, "analyzing", settings.job_lease_seconds)
        logger.info("job %s analyzing part %d/%d", job.id, part, parts)

    output = run_review(
        provider,
        rules,
        row.job_type or "design",
        blocks,
        max_chunk_chars=settings.analysis_chunk_chars,
        external=mode == "commercial" and provider.provider != "fake",
        on_part=on_part,
    )
    heartbeat(db, job, "validating", settings.job_lease_seconds)

    # 결과 저장과 상태 변경은 한 트랜잭션. 점유를 잃었으면 아무것도 남기지 않는다
    lock_own_job(db, job)
    for r in output.results:
        db.add(
            AnalysisResult(
                job_id=job.id,
                rule_id=r.rule_id,
                rule_version=RULES_VERSION,
                status=r.status,
                review_level=r.review_level,
                title=r.title,
                explanation=r.explanation,
                user_action=r.user_action or None,
                suggestion=r.suggestion or None,
                evidence=[
                    {"block_key": e.block_key, "page_no": e.page_no, "quote": e.quote, "valid": e.valid}
                    for e in r.evidence
                ],
                validation_status=r.validation,
                model_id=output.model_id,
                raw_response={"risk_level": r.risk_level, "validation_note": r.validation_note},
            )
        )
    row.model_config_ = {
        **(row.model_config_ or {}),
        "model_id": output.model_id,
        "provider": provider.provider,
        "input_tokens": output.input_tokens,
        "output_tokens": output.output_tokens,
        "parts": output.parts,
    }
    row.rules_version = RULES_VERSION
    row.prompt_version = PROMPT_VERSION
    version.status = "analyzed"
    if not finish_job(db, job, "succeeded"):
        raise RuntimeError("job ownership changed during save")
    db.commit()
