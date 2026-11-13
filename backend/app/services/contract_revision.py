"""청구 후 수정 계약 반영 (계약_변경_반영_설계.md).

발행 기록은 고치지 않는다. 청구가 있던 옛 지급 단계를 새 단계로 잇는 승계 행만 추가하고,
단계 한도는 계보 전체 청구액으로 검사한다 (DB 트리거 0005가 한 번 더 막는다).
"""

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select, text, update
from sqlalchemy.orm import Session

from app.core.audit import record_audit
from app.core.clock import now_utc
from app.core.errors import AppError, conflict, not_found
from app.core.versioning import assert_version
from app.db.models import (
    BillingAllocation,
    Contract,
    ContractVersion,
    Invoice,
    InvoiceItem,
    PaymentTerm,
    PaymentTermSuccession,
    Project,
)
from app.schemas.revision import (
    CarryIn,
    InvoiceRef,
    NewTermDraft,
    OldTerm,
    RevisionDraft,
    RevisionIn,
    VersionInfo,
)
from app.services.contracts import confirmed_values
from app.services.invoices import allocated_by_term, project_terms
from app.services.lineage import TERM_LINEAGE_CTE
from app.services.payment_terms import parse_payment_terms

ZERO = Decimal(0)


def _target_version(
    db: Session, project: Project, version_id: UUID
) -> tuple[ContractVersion, ContractVersion]:
    """(현재 버전, 반영할 버전). 같은 계약의 더 새로운, 조건 확인을 마친 버전만 받는다."""
    if project.contract_version_id is None:
        raise conflict("project_has_no_contract", "link a contract before applying a revision")
    current = db.get(ContractVersion, project.contract_version_id)
    target = db.execute(
        select(ContractVersion).where(
            ContractVersion.id == version_id, ContractVersion.owner_id == project.owner_id
        )
    ).scalar_one_or_none()
    if current is None or target is None:
        raise not_found("contract version")
    if target.contract_id != current.contract_id:
        raise conflict("revision_other_contract", "a revision must be a newer version of the same contract")
    if target.version_no <= current.version_no:
        raise conflict("revision_not_newer", "the version is not newer than the one the project uses")
    if target.status not in ("ready", "analyzed"):
        raise conflict("contract_not_confirmed", "confirm the contract fields first")
    return current, target


def _version_info(db: Session, version: ContractVersion) -> VersionInfo:
    values = confirmed_values(db, version.id)
    due = values.get("final_due_date")
    return VersionInfo(
        id=version.id,
        version_no=version.version_no,
        contract_amount=Decimal(values.get("contract_amount") or 0),
        due_date=date.fromisoformat(due) if due else None,
    )


def _term_invoices(db: Session, term_ids: list[UUID]) -> dict[UUID, list[InvoiceRef]]:
    """단계마다 (계보 포함) 취소되지 않은 인보이스"""
    if not term_ids:
        return {}
    rows = db.execute(
        text(
            TERM_LINEAGE_CTE  # noqa: S608 - 상수 조각만 이어 붙인다
            + """
            SELECT l.root_id, i.id, i.invoice_no, i.status, sum(ba.amount) AS amount
              FROM lineage l
              JOIN billing_allocations ba ON ba.payment_term_id = l.term_id
              JOIN invoice_items ii ON ii.id = ba.invoice_item_id
              JOIN invoices i ON i.id = ii.invoice_id
             WHERE i.status <> 'cancelled'
             GROUP BY l.root_id, i.id, i.invoice_no, i.status, i.created_at
             ORDER BY i.created_at
            """
        ),
        {"ids": term_ids},
    ).all()
    out: dict[UUID, list[InvoiceRef]] = defaultdict(list)
    for root, inv_id, no, status, amount in rows:
        out[root].append(InvoiceRef(id=inv_id, invoice_no=no, status=status, amount=amount))
    return out


def _old_terms(db: Session, project: Project) -> list[OldTerm]:
    terms = project_terms(db, project)
    ids = [t.id for t in terms]
    issued = allocated_by_term(db, ids, ("issued",))
    drafted = allocated_by_term(db, ids, ("draft",))
    invoices = _term_invoices(db, ids)
    return [
        OldTerm(
            term_id=t.id,
            seq=t.seq,
            stage=t.stage,
            label=t.label,
            amount=t.amount,
            billed=issued.get(t.id, ZERO),
            drafted=drafted.get(t.id, ZERO),
            invoices=invoices.get(t.id, []),
            must_carry=bool(invoices.get(t.id)),
        )
        for t in terms
    ]


def propose_carry(old_terms: list[OldTerm], new_terms: list[NewTermDraft]) -> list[CarryIn]:
    """같은 단계·같은 순서 → 같은 단계 → 남은 한도가 가장 큰 단계 순으로 제안한다."""
    room = {t.key: t.amount for t in new_terms}
    by_stage: dict[str, list[NewTermDraft]] = defaultdict(list)
    for t in new_terms:
        by_stage[t.stage].append(t)
    old_by_stage: dict[str, list[OldTerm]] = defaultdict(list)
    for o in old_terms:
        old_by_stage[o.stage].append(o)

    carry: list[CarryIn] = []
    for o in old_terms:
        if not o.must_carry:
            continue
        need = o.billed + o.drafted
        same = by_stage.get(o.stage, [])
        index = old_by_stage[o.stage].index(o)
        candidates = ([same[index]] if index < len(same) else []) + same + new_terms
        target = next((c for c in candidates if room[c.key] >= need), None)
        if target is None:
            target = max(new_terms, key=lambda c: room[c.key])
        room[target.key] -= need
        carry.append(CarryIn(from_term_id=o.term_id, to_key=target.key))
    return carry


def build_draft(db: Session, project: Project, version_id: UUID) -> RevisionDraft:
    current, target = _target_version(db, project, version_id)
    contract = db.get(Contract, target.contract_id)
    if contract is None:
        raise not_found("contract")
    values = confirmed_values(db, target.id)
    to_info = _version_info(db, target)
    parsed = parse_payment_terms(values.get("payment_terms"), to_info.contract_amount)
    new_terms = [
        NewTermDraft(
            key=f"t{t.seq}",
            stage=t.stage,  # type: ignore[arg-type]
            label=t.label,
            ratio=t.ratio,
            amount=t.amount,
            requirement=t.requirement,
        )
        for t in parsed
    ] or [
        NewTermDraft(
            key="t1", stage="other", label="일시불 100%", ratio=Decimal(100), amount=to_info.contract_amount
        )
    ]
    old = _old_terms(db, project)
    return RevisionDraft(
        project_id=project.id,
        contract_id=contract.id,
        contract_title=contract.title,
        from_version=VersionInfo(
            id=current.id,
            version_no=current.version_no,
            contract_amount=project.contract_amount,
            due_date=project.due_date,
        ),
        to_version=to_info,
        project_version=project.updated_at,
        old_terms=old,
        new_terms=new_terms,
        proposed_carry=propose_carry(old, new_terms),
        payment_terms_text=values.get("payment_terms"),
    )


def apply_revision(db: Session, user_id: UUID, project: Project, body: RevisionIn) -> None:
    """한 트랜잭션: 새 단계 생성 → 승계 기록 → 프로젝트 전환 → 초안 배분 이동"""
    assert_version(project.updated_at, body.version)
    current, target = _target_version(db, project, body.contract_version_id)
    db.execute(select(ContractVersion).where(ContractVersion.id == target.id).with_for_update())

    # 옛 단계를 잠가 그 사이의 발행을 막는다
    project_terms(db, project, lock=True)
    old = {o.term_id: o for o in _old_terms(db, project)}

    carry_map = {c.from_term_id: c.to_key for c in body.carry}
    missing = [o.label for o in old.values() if o.must_carry and o.term_id not in carry_map]
    if missing:
        raise AppError(
            422,
            "carry_missing",
            "every billed payment stage must continue into a new stage",
            {"stages": missing},
        )
    unknown = [str(tid) for tid in carry_map if tid not in old]
    not_needed = [old[tid].label for tid in carry_map if tid in old and not old[tid].must_carry]
    if unknown or not_needed:
        raise AppError(
            422,
            "carry_not_needed",
            "only billed stages of the current contract can be carried",
            {"stages": not_needed, "unknown": unknown},
        )

    carried_total = sum((o.billed + o.drafted for o in old.values()), ZERO)
    if carried_total > body.contract_amount:
        raise AppError(
            422,
            "amount_below_billed",
            "the new contract amount is lower than what has already been billed",
            {"billed": str(carried_total), "contract_amount": str(body.contract_amount)},
        )
    load: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for tid, key in carry_map.items():
        load[key] += old[tid].billed + old[tid].drafted
    terms_by_key = {t.key: t for t in body.payment_terms}
    over = [
        {"stage": terms_by_key[k].label, "amount": str(terms_by_key[k].amount), "carried": str(v)}
        for k, v in load.items()
        if v > terms_by_key[k].amount
    ]
    if over:
        raise AppError(422, "carry_exceeds_term", "carried billing exceeds the new stage amount", over)

    # 반영할 버전의 단계는 아직 청구된 적이 없어야 한다 (있으면 다른 흐름에서 쓰인 것)
    used = db.execute(
        select(BillingAllocation.id)
        .join(PaymentTerm, PaymentTerm.id == BillingAllocation.payment_term_id)
        .where(PaymentTerm.contract_version_id == target.id)
        .limit(1)
    ).first()
    if used:
        raise conflict("contract_has_billing", "the target version's payment stages are already billed")
    db.execute(delete(PaymentTerm).where(PaymentTerm.contract_version_id == target.id))

    now = now_utc()
    new_ids: dict[str, UUID] = {}
    for seq, term in enumerate(body.payment_terms, start=1):
        row = PaymentTerm(
            contract_version_id=target.id,
            seq=seq,
            stage=term.stage,
            label=term.label.strip(),
            ratio=term.ratio,
            amount=term.amount,
            requirement=(term.requirement or "").strip() or None,
            due_date=term.due_date,
            confirmed_by=user_id,
            confirmed_at=now,
        )
        db.add(row)
        db.flush()
        new_ids[term.key] = row.id

    for tid, key in carry_map.items():
        db.add(
            PaymentTermSuccession(
                owner_id=project.owner_id,
                project_id=project.id,
                predecessor_term_id=tid,
                successor_term_id=new_ids[key],
                created_by=user_id,
            )
        )

    project.contract_version_id = target.id
    project.contract_amount = body.contract_amount
    project.due_date = body.due_date
    db.flush()

    # 옛 단계를 가리키던 초안 배분은 이어진 새 단계로 옮긴다 (초안은 고칠 수 있는 문서)
    draft_items = (
        select(InvoiceItem.id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(Invoice.status == "draft", Invoice.project_id == project.id)
    )
    for tid, key in carry_map.items():
        db.execute(
            update(BillingAllocation)
            .where(
                BillingAllocation.payment_term_id == tid, BillingAllocation.invoice_item_id.in_(draft_items)
            )
            .values(payment_term_id=new_ids[key])
        )

    record_audit(
        db,
        actor_id=user_id,
        action="project.revise_contract",
        target_type="project",
        target_id=project.id,
        from_version_id=str(current.id),
        to_version_id=str(target.id),
        contract_amount=str(body.contract_amount),
        carry=[
            {
                "from": old[tid].label,
                "to": terms_by_key[key].label,
                "amount": str(old[tid].billed + old[tid].drafted),
            }
            for tid, key in carry_map.items()
        ],
    )
