"""확인된 지급 조건 문장을 지급 단계로 나눈다 (예: "계약 체결 후 선금 50%, 검수 완료 후 잔금 50%").

결과는 프로젝트 생성 화면의 초안일 뿐이고, 사용자가 단계·금액·요건을 고쳐서 저장한다.
비율 합이 100%면 원 단위 나머지를 마지막 단계에 붙여 합계가 계약 금액과 정확히 같게 만든다.
"""

import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from app.extraction.fields import STAGE_RATIO

STAGE_KIND = {
    "선금": "deposit",
    "계약금": "deposit",
    "착수금": "deposit",
    "중도금": "interim",
    "잔금": "balance",
}
DISPLAY_NAME = {"계약금": "선금", "착수금": "선금"}
SEPARATORS = re.compile(r"[,·ㆍ/\n]|그리고")


@dataclass(frozen=True)
class TermDraft:
    seq: int
    stage: str  # deposit | interim | balance | other
    label: str  # 선금 50%
    ratio: Decimal | None
    amount: Decimal
    requirement: str | None  # 계약 체결 후


def split_amount(total: Decimal, ratios: list[Decimal]) -> list[Decimal]:
    """비율대로 원 단위로 나눈다. 비율 합이 100이면 나머지는 마지막 단계에."""
    amounts = [(total * r / 100).quantize(Decimal(1), rounding=ROUND_DOWN) for r in ratios]
    if ratios and sum(ratios) == 100:
        amounts[-1] = total - sum(amounts[:-1])
    return amounts


def parse_payment_terms(text: str | None, total: Decimal) -> list[TermDraft]:
    if not text:
        return []
    found: list[tuple[str, Decimal, str | None]] = []
    for part in SEPARATORS.split(text):
        for match in STAGE_RATIO.finditer(part):
            name = re.sub(r"\s+", "", match.group(1))
            ratio = Decimal(match.group(2))
            requirement = part[: match.start()].strip(" ,.:;") or None
            found.append((name, ratio, requirement))
    if not found:
        return []

    amounts = split_amount(total, [r for _, r, _ in found])
    return [
        TermDraft(
            seq=i,
            stage=STAGE_KIND.get(name, "other"),
            label=f"{DISPLAY_NAME.get(name, name)} {ratio.normalize():f}%",
            ratio=ratio,
            amount=amount,
            requirement=requirement,
        )
        for i, ((name, ratio, requirement), amount) in enumerate(zip(found, amounts, strict=True), start=1)
    ]
