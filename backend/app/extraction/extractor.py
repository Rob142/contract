"""페이지별 텍스트 추출 (설계서 3장).

1. 텍스트 레이어를 먼저 읽는다.
2. 글자가 거의 없거나 깨진 글자가 많은 페이지만 이미지로 바꿔 OCR한다.
3. 줄 단위 블록에 페이지 번호·위치(PDF 포인트, 왼쪽 위 원점)·품질을 함께 남긴다.
없는 내용을 만들어 내지 않는다: 읽지 못한 페이지는 비워 두고 확인 필요로 표시한다.
"""

import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Literal

import pdfplumber

from app.extraction.ocr import OcrEngine

Method = Literal["text", "ocr"]

# pdfminer가 글리프를 유니코드로 바꾸지 못하면 "(cid:123)"을 낸다
CID_PATTERN = re.compile(r"\(cid:\d+\)")
GOOD_CHAR = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ0-9A-Za-z\s.,:;()\[\]%·\-~/'\"₩원@&+*#!?<>=_|]")

TEXT_QUALITY_THRESHOLD = 0.85


@dataclass
class Block:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float

    def bbox(self) -> dict[str, float]:
        return {
            "x0": round(self.x0, 1),
            "top": round(self.top, 1),
            "x1": round(self.x1, 1),
            "bottom": round(self.bottom, 1),
        }


@dataclass
class PageResult:
    page_no: int
    method: Method
    quality: float
    needs_review: bool
    width: float
    height: float
    blocks: list[Block] = field(default_factory=list)


class ExtractionCancelledError(Exception):
    pass


def text_quality(text: str) -> float:
    """읽을 수 있는 글자의 비율 (0~1). 깨진 글리프·대체 문자가 많으면 낮아진다."""
    cleaned = CID_PATTERN.sub("�", text)
    chars = [c for c in cleaned if not c.isspace()]
    if not chars:
        return 0.0
    good = sum(1 for c in chars if GOOD_CHAR.match(c))
    return good / len(chars)


def _text_layer(page: pdfplumber.page.Page) -> list[Block]:
    lines = page.extract_text_lines(layout=False, strip=True, return_chars=False)
    return [
        Block(text=ln["text"], x0=ln["x0"], top=ln["top"], x1=ln["x1"], bottom=ln["bottom"])
        for ln in lines
        if ln["text"].strip()
    ]


def _ocr_page(page: pdfplumber.page.Page, engine: OcrEngine, dpi: int) -> tuple[list[Block], float]:
    scale = 72 / dpi  # 픽셀 → PDF 포인트
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "page.png"
        page.to_image(resolution=dpi).original.save(image_path)
        lines = engine.recognize(image_path)
    blocks = [
        Block(text=ln.text, x0=ln.x0 * scale, top=ln.top * scale, x1=ln.x1 * scale, bottom=ln.bottom * scale)
        for ln in lines
    ]
    confidence = sum(ln.confidence for ln in lines) / len(lines) if lines else 0.0
    return blocks, confidence


def extract_pdf(
    stream: BinaryIO,
    *,
    ocr: OcrEngine | None,
    ocr_dpi: int,
    min_chars: int,
    on_page: Callable[[int, int, Method | None], None] = lambda *_: None,
) -> list[PageResult]:
    """on_page(page_no, total, method)는 페이지마다 불린다. 점유 갱신·취소 확인에 쓴다."""
    results: list[PageResult] = []
    with pdfplumber.open(stream, password="") as pdf:  # type: ignore[arg-type]
        total = len(pdf.pages)
        for index, page in enumerate(pdf.pages, start=1):
            on_page(index, total, None)
            blocks = _text_layer(page)
            text = "\n".join(b.text for b in blocks)
            quality = text_quality(text)
            char_count = sum(1 for c in text if not c.isspace())
            needs_ocr = char_count < min_chars or quality < TEXT_QUALITY_THRESHOLD

            if needs_ocr and ocr is not None:
                on_page(index, total, "ocr")
                ocr_blocks, confidence = _ocr_page(page, ocr, ocr_dpi)
                results.append(
                    PageResult(
                        page_no=index,
                        method="ocr",
                        quality=confidence,
                        # OCR 페이지는 엔진 신뢰도와 상관없이 항상 원문 비교를 요청한다.
                        # 신뢰도가 높아도 숫자를 잘못 읽는 경우가 있다 (1,000,000원 → 11000,000).
                        needs_review=True,
                        width=float(page.width),
                        height=float(page.height),
                        blocks=ocr_blocks,
                    )
                )
            else:
                results.append(
                    PageResult(
                        page_no=index,
                        method="text",
                        quality=quality,
                        # OCR을 쓸 수 없어 품질이 낮은 텍스트를 그대로 둔 경우도 확인 필요
                        needs_review=needs_ocr,
                        width=float(page.width),
                        height=float(page.height),
                        blocks=blocks,
                    )
                )
    return results
