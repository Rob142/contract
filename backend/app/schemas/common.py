from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, PlainSerializer

JobType = Literal[
    "dev",
    "design",
    "video",
    "marketing",
    "writing",
    "translation",
    "education",
    "consulting",
    "photography",
    "other",
]

# 원 단위 정수 금액. 입력은 숫자·문자열 모두 받고, 응답은 항상 십진 문자열이다 (부동소수점 금지)
Won = Annotated[
    Decimal,
    Field(ge=0, max_digits=14, decimal_places=0),
    PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json"),
]

Hours = Annotated[
    Decimal,
    Field(ge=0, max_digits=8, decimal_places=2),
    PlainSerializer(lambda v: format(v, "f"), return_type=str, when_used="json"),
]
