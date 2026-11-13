"""인보이스·입금확인서 PDF (설계서 6장).

- 인보이스는 발행 스냅샷만으로 그린다. 발행 후 프로젝트·작업이 바뀌어도 금액이 변하지 않는다.
- 입금확인서는 해당 입금 기록을 근거로 이번 입금액·누적 입금액·잔액을 나눠 적는다.
- 세금계산서·법정 현금영수증이 아니라는 점을 문서에 명시한다.
"""

import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = "/usr/share/fonts/truetype/nanum"
GREEN = colors.HexColor("#0b7d6e")
MUTED = colors.HexColor("#6b7280")
LINE = colors.HexColor("#e3e7ea")

NOT_TAX_DOCUMENT = "이 문서는 세금계산서 또는 법정 현금영수증이 아닙니다."


@lru_cache
def _fonts() -> tuple[str, str]:
    pdfmetrics.registerFont(TTFont("Nanum", f"{FONT_DIR}/NanumGothic.ttf"))
    pdfmetrics.registerFont(TTFont("Nanum-Bold", f"{FONT_DIR}/NanumGothicBold.ttf"))
    return "Nanum", "Nanum-Bold"


def won(value: Decimal | str | None) -> str:
    if value is None or value == "":
        return "—"
    return f"{int(Decimal(value)):,}원"


def ymd(value: date | str | None) -> str:
    if not value:
        return "—"
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{d.year}년 {d.month}월 {d.day}일"


def _styles() -> dict[str, ParagraphStyle]:
    regular, bold = _fonts()
    base = ParagraphStyle("base", fontName=regular, fontSize=9.5, leading=15)
    return {
        "base": base,
        "muted": ParagraphStyle("muted", parent=base, textColor=MUTED, fontSize=8.5, leading=13),
        "eyebrow": ParagraphStyle("eyebrow", parent=base, textColor=MUTED, fontSize=8, leading=12),
        "title": ParagraphStyle(
            "title", parent=base, fontName=bold, fontSize=22, leading=30, alignment=TA_CENTER
        ),
        "label": ParagraphStyle("label", parent=base, textColor=MUTED, fontSize=8.5),
        "strong": ParagraphStyle("strong", parent=base, fontName=bold, fontSize=11, leading=16),
        "right": ParagraphStyle("right", parent=base, alignment=TA_RIGHT),
        "total": ParagraphStyle(
            "total", parent=base, fontName=bold, fontSize=17, leading=24, alignment=TA_RIGHT, textColor=GREEN
        ),
        "center_muted": ParagraphStyle("cm", parent=base, textColor=MUTED, fontSize=8, alignment=TA_CENTER),
    }


def _esc(value: Any) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _party_table(left: list[str], right: list[str], s: dict[str, ParagraphStyle]) -> Table:
    def cell(lines: list[str]) -> list[Paragraph]:
        label, name, *rest = lines
        return [Paragraph(label, s["label"]), Paragraph(_esc(name), s["strong"])] + [
            Paragraph(_esc(x), s["muted"]) for x in rest if x
        ]

    table = Table([[cell(left), cell(right)]], colWidths=[85 * mm, 85 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _render(story: list[Any], title: str) -> bytes:
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="Freelance Hub",
    )
    doc.build(story)
    return out.getvalue()


def invoice_pdf(
    invoice_no: str, issue_date: date | None, due_date: date | None, snapshot: dict[str, Any]
) -> bytes:
    s = _styles()
    issuer, client = snapshot["issuer"], snapshot["client"]
    story: list[Any] = [
        Paragraph(f"INVOICE · {_esc(invoice_no)}", s["eyebrow"]),
        Spacer(1, 6 * mm),
        Paragraph("인보이스", s["title"]),
        Spacer(1, 10 * mm),
        _party_table(
            [
                "발행자",
                issuer.get("display_name") or issuer["name"],
                issuer["name"] if issuer.get("display_name") else "",
                issuer.get("contact"),
            ],
            ["청구 대상", client["name"], snapshot["project"]["name"], client.get("contact_email")],
            s,
        ),
        Spacer(1, 4 * mm),
        Paragraph(f"발행일 {ymd(issue_date)}", s["muted"]),
        Spacer(1, 6 * mm),
    ]

    label_right = ParagraphStyle("label_right", parent=s["label"], alignment=TA_RIGHT)
    rows: list[list[Any]] = [
        [
            Paragraph("항목", s["label"]),
            Paragraph("수량", label_right),
            Paragraph("단가", label_right),
            Paragraph("금액", label_right),
        ]
    ]
    for item in snapshot["items"]:
        desc = f"<b>{_esc(item['description'])}</b>"
        if item.get("detail"):
            desc += f"<br/><font color='#6b7280' size='8.5'>{_esc(item['detail'])}</font>"
        if item.get("payment_term"):
            term = item["payment_term"]
            basis = f"계약 지급 조건: {_esc(term['label'])}"
            if term.get("requirement"):
                basis += f" ({_esc(term['requirement'])})"
            desc += f"<br/><font color='#6b7280' size='8'>{basis}</font>"
        quantity = Decimal(item["quantity"])
        rows.append(
            [
                Paragraph(desc, s["base"]),
                Paragraph(f"{quantity.normalize():f}", s["right"]),
                Paragraph(won(item["unit_price"]), s["right"]),
                Paragraph(won(item["amount"]), s["right"]),
            ]
        )
    items = Table(rows, colWidths=[90 * mm, 18 * mm, 31 * mm, 31 * mm], repeatRows=1)
    items.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
                ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story += [items, Spacer(1, 4 * mm)]

    totals: list[list[Any]] = [
        [Paragraph("공급가액", s["muted"]), Paragraph(won(snapshot["subtotal"]), s["right"])]
    ]
    if Decimal(snapshot["tax_amount"]):
        totals.append([Paragraph("세액", s["muted"]), Paragraph(won(snapshot["tax_amount"]), s["right"])])
    if Decimal(snapshot["withholding_amount"]):
        totals.append(
            [
                Paragraph("원천징수", s["muted"]),
                Paragraph(f"−{won(snapshot['withholding_amount'])}", s["right"]),
            ]
        )
    totals.append(
        [Paragraph("<b>총 청구 금액</b>", s["base"]), Paragraph(won(snapshot["total"]), s["total"])]
    )
    total_table = Table(totals, colWidths=[110 * mm, 60 * mm])
    total_table.setStyle(
        TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])
    )
    story += [total_table, Spacer(1, 6 * mm)]

    story.append(Paragraph(f"지급 기한 {ymd(due_date)}", s["base"]))
    if issuer.get("bank_name") or issuer.get("bank_account"):
        story.append(
            Paragraph(
                f"입금 계좌 {_esc(issuer.get('bank_name'))} {_esc(issuer.get('bank_account'))}", s["base"]
            )
        )
    if snapshot.get("adjustment_note"):
        story.append(Paragraph(f"조정 근거: {_esc(snapshot['adjustment_note'])}", s["muted"]))
    story += [
        Spacer(1, 14 * mm),
        Paragraph("입금 계좌와 금액은 발행 시점에 확인한 정보로 표시됩니다.", s["center_muted"]),
        Paragraph(NOT_TAX_DOCUMENT, s["center_muted"]),
    ]
    return _render(story, f"인보이스 {invoice_no}")


@dataclass(frozen=True)
class ReceiptFacts:
    invoice_no: str
    invoice_title: str
    invoice_total: Decimal
    paid_on: date
    amount: Decimal
    cumulative_paid: Decimal  # 이 입금까지의 누적 (취소된 입금 제외)
    method: str
    memo: str | None
    snapshot: dict[str, Any]


METHOD_LABELS = {"bank_transfer": "계좌 입금", "cash": "현금", "card": "카드", "other": "기타"}


def receipt_pdf(facts: ReceiptFacts) -> bytes:
    s = _styles()
    issuer, client = facts.snapshot["issuer"], facts.snapshot["client"]
    balance = facts.invoice_total - facts.cumulative_paid
    rows = [
        ("관련 인보이스", f"{facts.invoice_no} · {facts.invoice_title}"),
        ("총 청구 금액", won(facts.invoice_total)),
        ("이번 입금액", won(facts.amount)),
        ("입금일", ymd(facts.paid_on)),
        ("입금 방법", METHOD_LABELS.get(facts.method, facts.method)),
        ("누적 입금액", won(facts.cumulative_paid)),
        ("남은 잔액", won(balance) if balance > 0 else "0원 (완납)"),
    ]
    if facts.memo:
        rows.append(("메모", facts.memo))
    table = Table(
        [[Paragraph(k, s["label"]), Paragraph(_esc(v), s["base"])] for k, v in rows],
        colWidths=[40 * mm, 130 * mm],
    )
    table.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story: list[Any] = [
        Paragraph(f"PAYMENT CONFIRMATION · {_esc(facts.invoice_no)}", s["eyebrow"]),
        Spacer(1, 6 * mm),
        Paragraph("입금확인서", s["title"]),
        Spacer(1, 10 * mm),
        _party_table(
            ["확인자(수령인)", issuer.get("display_name") or issuer["name"], issuer.get("contact")],
            ["입금인", client["name"], facts.snapshot["project"]["name"]],
            s,
        ),
        Spacer(1, 8 * mm),
        table,
        Spacer(1, 8 * mm),
        Paragraph(
            f"위 금액이 {ymd(facts.paid_on)}에 입금되었음을 확인합니다. "
            "이 확인은 은행 연동 결과가 아니라 수령인이 직접 확인해 기록한 입금 내역을 근거로 합니다.",
            s["base"],
        ),
        Spacer(1, 14 * mm),
        Paragraph(NOT_TAX_DOCUMENT, s["center_muted"]),
    ]
    return _render(story, f"입금확인서 {facts.invoice_no}")
