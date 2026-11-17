"""작업자 프로세스: python -m app.worker

웹 요청과 분리된 프로세스에서 무거운 처리를 한다 (설계서 5장).
"""

import logging
import signal
import time
from types import FrameType

from sqlalchemy.orm import Session

from app.analysis.llm import LlmOutputError, LlmTransientError, LlmUnavailableError
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.storage import get_storage
from app.db.models import AnalysisJob
from app.db.session import get_sessionmaker
from app.extraction.extractor import ExtractionCancelledError
from app.extraction.ocr import OcrError, get_ocr_engine
from app.worker.analyze_job import run_analyze
from app.worker.extract_job import PermanentJobError, mark_version, run_extract
from app.worker.queue import (
    ClaimedJob,
    JobCancelledError,
    LeaseLostError,
    claim_job,
    finish_job,
    reap_expired,
    requeue_job,
)

logger = logging.getLogger("app.worker")

_stopping = False


def _stop(signum: int, _frame: FrameType | None) -> None:
    global _stopping
    _stopping = True
    logger.info("received signal %d, finishing current job then exiting", signum)


def _restore_analysis_status(db: Session, job: ClaimedJob) -> None:
    """분석이 끝나지 못하면 계약서는 분석 전 상태(확인 완료 또는 이전 분석 완료)로 돌아간다."""
    row = db.get(AnalysisJob, job.id)
    previous = (row.input or {}).get("previous_status", "ready") if row else "ready"
    mark_version(db, job.contract_version_id, previous)


def process(job: ClaimedJob) -> None:
    if job.kind == "analyze":
        process_analyze(job)
    else:
        process_extract(job)


def process_extract(job: ClaimedJob) -> None:
    settings = get_settings()
    ocr = get_ocr_engine(settings.ocr_engine, settings.ocr_languages)
    with get_sessionmaker()() as db:
        try:
            run_extract(db, job, settings, get_storage(), ocr)
            logger.info("job %s succeeded", job.id)
        except ExtractionCancelledError:
            db.rollback()
            if finish_job(db, job, "cancelled"):
                mark_version(db, job.contract_version_id, "failed", "cancelled")
            db.commit()
            logger.info("job %s cancelled", job.id)
        except LeaseLostError:
            db.rollback()
            logger.warning("job %s lost its lease; result discarded", job.id)
        except PermanentJobError as exc:
            db.rollback()
            if finish_job(db, job, "failed", exc.code, str(exc)):
                mark_version(db, job.contract_version_id, "failed", exc.code)
            db.commit()
            logger.info("job %s failed: %s", job.id, exc.code)
        except Exception as exc:  # noqa: BLE001 - 일시적 오류는 재시도
            db.rollback()
            code = "ocr_error" if isinstance(exc, OcrError) else "internal_error"
            if requeue_job(db, job, code, type(exc).__name__):
                mark_version(db, job.contract_version_id, "uploaded")
                logger.warning("job %s will retry after %s", job.id, type(exc).__name__)
            elif finish_job(db, job, "failed", code, type(exc).__name__):
                mark_version(db, job.contract_version_id, "failed", code)
                logger.exception("job %s failed permanently", job.id)
            db.commit()


def process_analyze(job: ClaimedJob) -> None:
    """실패해도 계약서 확인값·추출 텍스트는 그대로 두고, 분석 작업만 실패로 남긴다."""
    settings = get_settings()
    with get_sessionmaker()() as db:
        try:
            run_analyze(db, job, settings)
            logger.info("job %s succeeded", job.id)
        except JobCancelledError:
            db.rollback()
            if finish_job(db, job, "cancelled"):
                _restore_analysis_status(db, job)
            db.commit()
        except LeaseLostError:
            db.rollback()
            logger.warning("job %s lost its lease; result discarded", job.id)
        except (PermanentJobError, LlmUnavailableError, LlmOutputError) as exc:
            db.rollback()
            if finish_job(db, job, "failed", exc.code, str(exc)[:300]):
                _restore_analysis_status(db, job)
            db.commit()
            logger.info("job %s failed: %s", job.id, exc.code)
        except Exception as exc:  # noqa: BLE001 - 통신 오류 등은 재시도
            db.rollback()
            code = exc.code if isinstance(exc, LlmTransientError) else "internal_error"
            if requeue_job(db, job, code, type(exc).__name__):
                logger.warning("job %s will retry after %s", job.id, type(exc).__name__)
            elif finish_job(db, job, "failed", code, type(exc).__name__):
                _restore_analysis_status(db, job)
                logger.exception("job %s failed permanently", job.id)
            db.commit()


def main() -> None:
    configure_logging()
    settings = get_settings()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("worker started (ocr=%s)", settings.ocr_engine)

    maker = get_sessionmaker()
    while not _stopping:
        try:
            with maker() as db:
                reaped = reap_expired(db)
                if reaped:
                    logger.warning("reclaimed %d expired job(s)", reaped)
                job = claim_job(db, ["extract", "analyze"], settings.job_lease_seconds)
        except Exception:
            logger.exception("queue error; retrying")
            time.sleep(settings.worker_poll_seconds * 2)
            continue

        if job is None:
            time.sleep(settings.worker_poll_seconds)
            continue
        logger.info("claimed job %s (%s, attempt %d/%d)", job.id, job.kind, job.attempts, job.max_attempts)
        process(job)

    logger.info("worker stopped")


if __name__ == "__main__":
    main()
