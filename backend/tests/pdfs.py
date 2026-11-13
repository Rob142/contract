"""테스트용 PDF 생성기 (외부 라이브러리 없이 최소 구조만 쓴다)."""

import io

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(pages: list[list[str]]) -> bytes:
    """페이지마다 줄 목록을 Helvetica로 쓴 텍스트 PDF. 빈 목록이면 글자 없는(스캔 같은) 페이지."""
    objects: list[bytes] = []
    page_ids: list[int] = []
    # 1: catalog, 2: pages, 3: font, 이후 페이지·내용 객체
    next_id = 4
    page_objects: list[tuple[int, bytes]] = []
    for lines in pages:
        content = (
            "BT /F1 12 Tf 16 TL 72 740 Td " + " ".join(f"({_escape(line)}) Tj T*" for line in lines) + " ET"
        )
        stream = content.encode("latin-1")
        content_id, page_id = next_id, next_id + 1
        next_id += 2
        page_objects.append(
            (content_id, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        )
        page_objects.append(
            (
                page_id,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id,
            )
        )
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    by_id = dict(page_objects)
    objects += [by_id[i] for i in range(4, next_id)]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def image_pdf(lines: list[str]) -> bytes:
    """글자를 그림으로만 담은 PDF (스캔 문서 흉내). OCR 테스트용."""
    image = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=56)
    for i, line in enumerate(lines):
        draw.text((150, 200 + i * 110), line, fill="black", font=font)
    out = io.BytesIO()
    image.save(out, format="PDF", resolution=200)
    return out.getvalue()


def encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(user_password="secret", owner_password="owner", algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
