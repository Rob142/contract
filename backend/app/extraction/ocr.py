"""OCR 엔진 경계 (설계서 3장: 교체 가능한 처리 모듈).

엔진은 페이지 이미지 하나를 받아 줄 단위 결과를 돌려준다. 좌표는 이미지 픽셀 기준이다.
Rust 기반 엔진 등은 OcrEngine을 구현해 get_ocr_engine에 등록하면 된다.
"""

import csv
import io
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class OcrLine:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    confidence: float  # 0~1


class OcrError(Exception):
    pass


class OcrEngine(Protocol):
    name: str

    def recognize(self, image_path: Path) -> list[OcrLine]: ...


class TesseractOcr:
    name = "tesseract"

    def __init__(self, languages: str, timeout_seconds: int = 120) -> None:
        self.languages = languages
        self.timeout_seconds = timeout_seconds

    def recognize(self, image_path: Path) -> list[OcrLine]:
        try:
            result = subprocess.run(  # noqa: S603 - 고정된 실행 파일과 인자만 쓴다
                ["tesseract", str(image_path), "stdout", "-l", self.languages, "--psm", "3", "tsv"],  # noqa: S607
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrError("tesseract timed out") from exc
        if result.returncode != 0:
            raise OcrError(f"tesseract failed: {result.stderr.decode(errors='replace')[:200]}")
        return parse_tesseract_tsv(result.stdout.decode("utf-8", errors="replace"))


def parse_tesseract_tsv(tsv: str) -> list[OcrLine]:
    """단어(level 5)를 블록·문단·줄 번호로 묶어 줄 단위 결과로 만든다."""
    lines: dict[tuple[int, int, int], list[dict[str, str]]] = defaultdict(list)
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not (row.get("text") or "").strip():
            continue
        lines[(int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))].append(row)

    result: list[OcrLine] = []
    for _, words in sorted(lines.items()):
        lefts = [int(w["left"]) for w in words]
        tops = [int(w["top"]) for w in words]
        rights = [int(w["left"]) + int(w["width"]) for w in words]
        bottoms = [int(w["top"]) + int(w["height"]) for w in words]
        confs = [max(float(w["conf"]), 0.0) for w in words]
        result.append(
            OcrLine(
                text=" ".join(w["text"].strip() for w in words),
                x0=min(lefts),
                top=min(tops),
                x1=max(rights),
                bottom=max(bottoms),
                confidence=sum(confs) / len(confs) / 100,
            )
        )
    return result


def get_ocr_engine(name: str, languages: str) -> OcrEngine | None:
    if name == "tesseract":
        return TesseractOcr(languages)
    if name == "none":
        return None
    raise ValueError(f"unknown OCR engine: {name}")
