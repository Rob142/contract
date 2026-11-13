"""핵심 항목 후보 찾기: 계약 금액, 최종 납기, 지급 조건, 수정 횟수.

규칙 기반으로 "후보"만 찾는다. 결과는 항상 미확정이며 사용자가 원문과 비교해 확정한다
(설계서 3장: OCR이 1,000,000원을 100,000원으로 읽어도 확인 전에는 어디에도 반영하지 않는다).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

FIELD_KEYS = ("contract_amount", "final_due_date", "payment_terms", "revision_count")
REQUIRED_FIELD_KEYS = ("contract_amount", "final_due_date", "payment_terms")


@dataclass(frozen=True)
class TextLine:
    key: str  # 블록 식별자 (p1-b007)
    text: str


@dataclass(frozen=True)
class FieldCandidate:
    key: str
    value: str
    block_key: str


def _spaced(*words: str) -> str:
    """OCR은 단어 중간에 공백을 넣는다 ("선 금"). 글자 사이 공백을 허용하는 대안 패턴."""
    return "(?:" + "|".join(r"\s*".join(map(re.escape, w)) for w in words) + ")"


# 금액은 쉼표 구분(1,000,000) 또는 구분 없는 숫자만 받는다.
# "1.000,000"처럼 구분자가 섞인 값은 오인식일 수 있어 후보로 내지 않는다 (사용자가 원문으로 확인).
AMOUNT = re.compile(
    _spaced("총 계약 금액", "계약 금액", "용역 대금", "총 금액", "대금", "금액")
    + r"[^0-9\n]{0,15}(?:금\s*)?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]{4,})\s*원"
)
DATE = r"(20\d{2})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?"
# 최종 납기: "최종 납품일은 …", "최종 산출물은 2026년 12월 4일까지 전달한다"
DUE = re.compile(
    r"(?:최\s*종\s*)?"
    + _spaced("납품", "납기", "인도", "산출물", "결과물", "납품물", "제출", "완료")
    + r"\s*(?:일|기한|일정|일자)?[^0-9\n]{0,20}"
    + DATE
)
# 대안: 계약 기간의 끝 날짜 ("계약 기간은 2026년 11월 16일부터 2026년 12월 4일까지")
PERIOD_END = re.compile(
    _spaced("계약 기간", "용역 기간", "수행 기간") + r"[^\n]{0,40}?" + DATE + r"[^\n]{0,8}?" + DATE
)
# 단계 이름과 비율 사이에 다른 말이 끼어도 된다: "선금은 총 계약 금액의 50%인"
STAGE_RATIO = re.compile(
    "(" + _spaced("선금", "계약금", "착수금", "중도금", "잔금") + r")[^0-9%\n]{0,20}?(\d{1,3})\s*%"
)
REVISION = re.compile(_spaced("수정") + r"\s*(?:횟수|요청)?[^0-9\n]{0,10}(\d{1,2})\s*회")

STAGE_NAMES = {"계약금": "선금", "착수금": "선금"}


def _iso(y: str, m: str, d: str) -> str | None:
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except ValueError:
        return None


# 쉼표·가운뎃점으로 나누되 금액 안의 쉼표(500,000)는 나누지 않는다
TERM_PARTS = re.compile(r"(?<!\d),|,(?!\d)|[·ㆍ]")
NUMBERING = re.compile(r"^\s*(?:\(?\d{1,2}[.)]|[①-⑳]|[-•])\s*")
PAY_CLAUSE = re.compile(r"^\s*(.*?)\s*(?:에|까지)?\s*(?:지급|지불|입금)")
MAX_REQUIREMENT_CHARS = 30


def _stage_terms(text: str) -> list[tuple[str, str]]:
    """한 줄에서 (단계 이름, "요건 단계 N%")를 찾는다.

    "계약 체결 후 선금 50%, 검수 완료 후 잔금 50%를 지급한다." → 요건이 단계 앞에 있다.
    "선금은 총 계약 금액의 50%인 500,000원으로 하며, 계약 체결일로부터 3영업일 이내에 지급한다."
    → 요건이 단계 뒤의 지급 문구에 있다.
    """
    parts = TERM_PARTS.split(text)
    terms: list[tuple[str, str]] = []
    for i, part in enumerate(parts):
        last = 0
        for m in STAGE_RATIO.finditer(part):
            requirement = NUMBERING.sub("", part[last : m.start()]).strip(" .:;")
            last = m.end()
            if not requirement:
                # 같은 줄 뒤쪽의 "… 이내에 지급한다"에서 요건을 가져온다
                for later in parts[i + 1 :]:
                    if STAGE_RATIO.search(later):
                        break
                    if clause := PAY_CLAUSE.search(later):
                        requirement = clause.group(1).strip(" .:;")
                        break
            if len(requirement) > MAX_REQUIREMENT_CHARS:
                requirement = ""
            name = re.sub(r"\s+", "", m.group(1))
            name = STAGE_NAMES.get(name, name)
            terms.append((name, f"{requirement} {name} {int(m.group(2))}%".strip()))
    return terms


def _payment_terms(text: str) -> str | None:
    """한 줄의 지급 조건 (요건 포함). 여러 줄에 걸친 경우는 find_fields가 모은다."""
    return " · ".join(t for _, t in _stage_terms(text)) or None


def find_fields(lines: Sequence[TextLine]) -> list[FieldCandidate]:
    found: dict[str, FieldCandidate] = {}
    period_end: FieldCandidate | None = None
    stages: dict[str, str] = {}  # 단계 이름 → "요건 단계 N%" (문서 순서, 처음 나온 것)
    stage_block: str | None = None

    for line in lines:
        text = line.text
        if "contract_amount" not in found and (m := AMOUNT.search(text)):
            found["contract_amount"] = FieldCandidate(
                "contract_amount", m.group(1).replace(",", ""), line.key
            )
        if "final_due_date" not in found and (m := DUE.search(text)):
            if iso := _iso(*m.group(1, 2, 3)):
                found["final_due_date"] = FieldCandidate("final_due_date", iso, line.key)
        if period_end is None and (m := PERIOD_END.search(text)):
            if iso := _iso(*m.group(4, 5, 6)):
                period_end = FieldCandidate("final_due_date", iso, line.key)
        for name, term in _stage_terms(text):
            if name not in stages:
                stages[name] = term
                stage_block = stage_block or line.key
        if "revision_count" not in found and (m := REVISION.search(text)):
            found["revision_count"] = FieldCandidate("revision_count", f"{int(m.group(1))}회", line.key)

    # 납품 문장이 없으면 계약 기간의 끝 날짜를 후보로 (사용자가 원문으로 확인)
    if "final_due_date" not in found and period_end is not None:
        found["final_due_date"] = period_end
    if stages and stage_block:
        found["payment_terms"] = FieldCandidate("payment_terms", " · ".join(stages.values()), stage_block)
    return [found[k] for k in FIELD_KEYS if k in found]
