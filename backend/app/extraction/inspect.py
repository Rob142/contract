"""업로드 시점의 PDF 검사 (설계서 3장): 실제 형식, 손상, 암호화, 페이지 수.

확장자나 Content-Type은 믿지 않고 파일 내용으로 판단한다.
"""

from dataclasses import dataclass
from typing import BinaryIO

from pypdf import PasswordType, PdfReader


@dataclass(frozen=True)
class PdfInfo:
    page_count: int


class PdfRejectedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


PDF_MAGIC = b"%PDF-"
HEADER_SCAN_BYTES = 1024


def looks_like_pdf(head: bytes) -> bool:
    # 사양상 헤더는 파일 앞 1024바이트 안에 있으면 된다
    return PDF_MAGIC in head[:HEADER_SCAN_BYTES]


def inspect_pdf(stream: BinaryIO, max_pages: int) -> PdfInfo:
    if not looks_like_pdf(stream.read(HEADER_SCAN_BYTES)):
        raise PdfRejectedError("not_pdf", "the file is not a PDF")
    stream.seek(0)

    try:
        reader = PdfReader(stream, strict=False)
        if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            # 열람 암호가 걸린 문서는 읽을 수 없다. 권한 암호만 있는 문서는 빈 암호로 열린다
            raise PdfRejectedError("encrypted_pdf", "password-protected PDFs cannot be read")
        page_count = len(reader.pages)
    except PdfRejectedError:
        raise
    except Exception as exc:  # pypdf는 손상 형태에 따라 여러 예외를 낸다
        raise PdfRejectedError("invalid_pdf", "the PDF is damaged or unreadable") from exc

    if page_count == 0:
        raise PdfRejectedError("invalid_pdf", "the PDF has no pages")
    if page_count > max_pages:
        raise PdfRejectedError("too_many_pages", f"the PDF has {page_count} pages (limit {max_pages})")
    return PdfInfo(page_count=page_count)
