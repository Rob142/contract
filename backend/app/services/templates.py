"""직군별 기본 단계 템플릿. 프로젝트 생성 때 작업으로 복사하며, 만든 뒤에는 자유롭게 고칠 수 있다."""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Task

# 직군 → 단계 제목 목록 (순서대로 정렬 순서가 된다)
JOB_TEMPLATES: dict[str, list[str]] = {
    "writing": ["주제·구성 협의", "초안 작성", "검토·수정", "최종 납품"],
    "translation": ["원문·용어 확인", "번역·통역 준비", "검수", "납품·완료"],
    "education": ["교육 목표 협의", "교안 준비", "교육 진행", "결과 정리"],
    "consulting": ["범위 협의", "자료 조사", "제안·자문", "최종 보고"],
    "photography": ["촬영 협의", "촬영", "보정·검수", "최종 납품"],
    "other": ["범위 협의", "작업 진행", "검수·수정", "최종 납품"],
    "dev": ["요구사항 정리", "설계", "개발", "테스트·수정", "배포·인수"],
    "design": ["착수·자료 수령", "시안 제작", "수정", "최종 납품"],
    "video": ["기획·콘티", "촬영", "편집", "수정", "최종 납품"],
    "marketing": ["목표·전략 수립", "콘텐츠 제작", "집행", "성과 보고"],
}


def template_for(job_type: str) -> list[str]:
    return list(JOB_TEMPLATES.get(job_type, []))


def step_due_dates(count: int, start: date | None, due: date | None) -> list[date | None]:
    """시작일~납기 사이를 단계 수로 나눠 단계별 마감일을 제안한다. 마지막 단계는 납기와 같다.

    시작일이나 납기가 없거나 기간이 거꾸로면 마감일을 비워 둔다.
    """
    if count == 0 or start is None or due is None or due < start:
        return [None] * count
    span = (due - start).days
    return [start + timedelta(days=round(span * (i + 1) / count)) for i in range(count)]


def apply_template(
    db: Session,
    project_id: UUID,
    job_type: str,
    start: date | None = None,
    due: date | None = None,
) -> int:
    """기존 작업 뒤에 템플릿 단계를 붙인다. 만든 개수를 돌려준다."""
    titles = template_for(job_type)
    first = db.execute(
        select(func.coalesce(func.max(Task.position) + 1, 0)).where(Task.project_id == project_id)
    ).scalar_one()
    dues = step_due_dates(len(titles), start, due)
    for offset, title in enumerate(titles):
        db.add(
            Task(
                project_id=project_id,
                title=title,
                position=first + offset,
                due_date=dues[offset],
                source="template",
            )
        )
    return len(titles)
