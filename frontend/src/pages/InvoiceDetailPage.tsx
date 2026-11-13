import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useOutletContext, useParams } from 'react-router'

import type { User } from '../api/auth'

import { ApiError } from '../api/client'
import {
  invoicePdfUrl,
  receiptPdfUrl,
  useCancelInvoice,
  useDeleteInvoice,
  useInvoice,
  useIssueInvoice,
  useRecordPayment,
  useReissueInvoice,
  useVoidPayment,
  type InvoiceDetail,
} from '../api/invoices'
import { messageOf } from '../api/messages'
import { AmountField } from '../components/AmountField'
import { Dialog } from '../components/Dialog'
import { SelectField, TextField } from '../components/Field'
import { LoadError, Loading, ProgressBar } from '../components/ui'
import { formatFullDate, formatMonthDay, formatWon, localDateOf, todayIso } from '../lib/format'
import { newIdempotencyKey } from '../lib/idempotency'
import { invoiceBadge, PAYMENT_METHOD_LABELS } from '../lib/invoiceStatus'
import { NotFoundPage } from './NotFoundPage'

type Snapshot = {
  issuer: { name: string; display_name: string | null; contact: string | null; bank_name: string | null; bank_account: string | null }
  client: { name: string }
  project: { name: string }
  contract: { title: string; version_no: number } | null
  items: { description: string; detail: string | null; quantity: string; unit_price: string; amount: string; payment_term: { label: string; requirement: string | null } | null }[]
}

/** 문서 미리보기: 발행본은 고정된 스냅샷으로, 초안은 현재 항목으로 그린다 */
function DocumentPreview({ invoice }: { invoice: InvoiceDetail }) {
  const snap = invoice.snapshot as Snapshot | null
  const items = snap
    ? snap.items
    : invoice.items.map((i) => ({ description: i.description, detail: i.detail, quantity: i.quantity, unit_price: i.unit_price, amount: i.amount, payment_term: null }))
  const quantity = (q: string) => q.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')

  return (
    <div className="doc-preview">
      <div className="doc-toolbar">
        <span className="muted">{snap ? '발행 문서 미리보기' : '초안 미리보기'}</span>
        <span className={invoice.status === 'draft' ? 'badge badge-gray' : invoice.status === 'cancelled' ? 'badge badge-red' : 'badge badge-green'}>
          {invoice.status === 'draft' ? '초안' : invoice.status === 'cancelled' ? '취소됨' : '발행 완료'}
        </span>
      </div>
      <div className="doc-frame">
        <article className={invoice.status === 'cancelled' ? 'doc-page is-void' : 'doc-page'}>
          <p className="doc-eyebrow">INVOICE · {invoice.invoice_no ?? 'DRAFT'}</p>
          <h2 className="doc-title">인보이스</h2>
          <div className="doc-parties">
            <div>
              <span className="muted small">발행자</span>
              <strong>{snap ? snap.issuer.display_name || snap.issuer.name : '발행 시 확정'}</strong>
              {snap?.issuer.contact && <span className="muted small">{snap.issuer.contact}</span>}
            </div>
            <div>
              <span className="muted small">청구 대상</span>
              <strong>{snap ? snap.client.name : invoice.client_name}</strong>
              <span className="muted small">{invoice.title}</span>
            </div>
          </div>
          <table className="doc-items">
            <tbody>
              {items.map((item, i) => (
                <tr key={i}>
                  <td>
                    <strong>{item.description}</strong>
                    {item.detail && <span className="muted small">{item.detail}</span>}
                    <span className="muted small">
                      수량 {quantity(item.quantity)} × 단가 {formatWon(item.unit_price)}
                    </span>
                  </td>
                  <td className="num">{formatWon(item.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(invoice.tax_amount !== '0' || invoice.withholding_amount !== '0') && (
            <p className="muted small doc-adjust">
              공급가액 {formatWon(invoice.subtotal)}
              {invoice.tax_amount !== '0' && ` · 세액 ${formatWon(invoice.tax_amount)}`}
              {invoice.withholding_amount !== '0' && ` · 원천징수 −${formatWon(invoice.withholding_amount)}`}
            </p>
          )}
          <div className="doc-total">
            <strong>총 청구 금액</strong>
            <span>{formatWon(invoice.total)}</span>
          </div>
          <p className="muted small">지급 기한 {invoice.due_date ? formatFullDate(invoice.due_date) : '미정'}</p>
          {snap?.issuer.bank_name && (
            <p className="muted small">
              입금 계좌 {snap.issuer.bank_name} {snap.issuer.bank_account}
            </p>
          )}
          <p className="doc-foot">입금 계좌와 금액은 발행 시 확인한 정보로 표시됩니다. 세금계산서가 아닙니다.</p>
        </article>
      </div>
    </div>
  )
}

/** 발행 전 점검표 (UX 문서 4장 A). 모두 통과해야 발행 버튼이 켜진다. */
function IssueDialog({ invoice, user, onClose }: { invoice: InvoiceDetail; user: User; onClose: () => void }) {
  const issue = useIssueInvoice(invoice.id)
  const [dueDate, setDueDate] = useState(invoice.due_date ?? '')
  const [key] = useState(newIdempotencyKey)

  const unconfirmed = invoice.items.filter((i) => i.kind === 'payment_stage' && !i.basis_confirmed_at)
  const issuerReady = Boolean(user.issuer_name && user.bank_name && user.bank_account && user.issuer_contact)
  const checks = [
    {
      ok: Boolean(dueDate),
      label: '지급 기한',
      note: dueDate ? `${formatFullDate(dueDate)}까지 입금 요청` : '지급 기한을 정해 주세요.',
    },
    {
      ok: unconfirmed.length === 0,
      label: '지급 요건 확인',
      note: unconfirmed.length
        ? `아직 요건을 확인하지 않은 단계가 있어요: ${unconfirmed.map((i) => i.description).join(', ')}`
        : '청구한 지급 단계의 요건을 모두 확인했어요.',
    },
    {
      ok: issuerReady,
      label: '발행자 정보 (상호·계좌·연락처)',
      note: issuerReady
        ? `${user.issuer_display_name || user.issuer_name} · ${user.bank_name} ${user.bank_account ?? ''}`
        : '문서에 고정할 발행자 정보가 비어 있어요.',
    },
  ]
  const allPass = checks.every((c) => c.ok)

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!allPass) return
    issue.mutate({ dueDate: dueDate || null, idempotencyKey: key }, { onSuccess: onClose })
  }
  return (
    <Dialog
      open
      onClose={onClose}
      title="인보이스 발행"
      footer={
        <>
          <span className="spacer" />
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            취소
          </button>
          <button type="submit" form="issue-form" className="btn btn-primary" disabled={!allPass || issue.isPending}>
            {issue.isPending ? '발행 중…' : `${formatWon(invoice.total)} 발행`}
          </button>
        </>
      }
    >
      <form id="issue-form" onSubmit={onSubmit} className="stack-sm">
        <p style={{ margin: 0 }}>
          발행하면 거래처·발행자 정보와 항목·금액이 이 시점 내용으로 고정되고 문서 번호가 붙어요. 이후에는 고칠 수 없고 취소 후 재발행만 할 수 있어요.
        </p>
        <TextField label="지급 기한" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
        <ul className="issue-checklist" aria-label="발행 전 점검">
          {checks.map((c) => (
            <li key={c.label} className={c.ok ? 'is-ok' : 'is-missing'}>
              <span className="issue-check-mark" aria-hidden="true">
                {c.ok ? '✓' : '!'}
              </span>
              <div>
                <strong>{c.label}</strong>
                <span className={c.ok ? 'muted small' : 'field-error small'}>
                  {c.note}
                  {!c.ok && c.label.startsWith('발행자') && (
                    <>
                      {' '}
                      <Link to="/settings" className="link-strong">
                        설정에서 입력 →
                      </Link>
                    </>
                  )}
                </span>
              </div>
            </li>
          ))}
        </ul>
        {!allPass && (
          <p className="field-hint" style={{ margin: 0 }}>
            점검 항목을 모두 통과하면 발행할 수 있어요.
          </p>
        )}
        {issue.isError && (
          <div className="alert alert-error" role="alert">
            {messageOf(issue.error)}
            {issue.error instanceof ApiError && issue.error.code === 'over_billed' && Array.isArray(issue.error.details) && (
              <ul className="small">
                {(issue.error.details as { payment_term: string; limit: string; already_billed: string }[]).map((d) => (
                  <li key={d.payment_term}>
                    {d.payment_term}: 한도 {formatWon(d.limit)}, 이미 청구 {formatWon(d.already_billed)}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </form>
    </Dialog>
  )
}

function PaymentDialog({ invoice, onClose }: { invoice: InvoiceDetail; onClose: () => void }) {
  const record = useRecordPayment(invoice.id)
  // 같은 입력을 다시 보내도 한 번만 기록되도록, 대화상자를 여는 동안 같은 키를 쓴다
  const [key] = useState(newIdempotencyKey)
  const [amount, setAmount] = useState(invoice.balance)
  const [paidOn, setPaidOn] = useState(todayIso())
  const [method, setMethod] = useState('bank_transfer')
  const [memo, setMemo] = useState('')
  const [checked, setChecked] = useState(false)
  const over = BigInt(amount || '0') > BigInt(invoice.balance)
  const valid = amount && BigInt(amount) > 0n && !over && paidOn && paidOn <= todayIso() && checked

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    record.mutate(
      { idempotencyKey: key, body: { amount, paid_on: paidOn, method: method as 'bank_transfer', memo: memo.trim() || null } },
      { onSuccess: onClose },
    )
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title="입금 기록"
      footer={
        <>
          <span className="spacer" />
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            취소
          </button>
          <button type="submit" form="payment-form" className="btn btn-primary" disabled={!valid || record.isPending}>
            {record.isPending ? '기록 중…' : '입금 기록'}
          </button>
        </>
      }
    >
      <form id="payment-form" onSubmit={onSubmit} className="form-grid" noValidate>
        <AmountField
          label="입금액"
          value={amount}
          onChange={setAmount}
          error={over ? `잔액 ${formatWon(invoice.balance)}보다 많이 기록할 수 없어요.` : undefined}
          fieldClassName="span-2"
        />
        <TextField label="입금일" type="date" value={paidOn} max={todayIso()} onChange={(e) => setPaidOn(e.target.value)} />
        <SelectField
          label="입금 방법"
          options={Object.entries(PAYMENT_METHOD_LABELS).map(([value, label]) => ({ value, label }))}
          value={method}
          onChange={(e) => setMethod(e.target.value)}
        />
        <TextField label="메모 (선택)" placeholder="예: 잔금 일부" value={memo} maxLength={300} onChange={(e) => setMemo(e.target.value)} fieldClassName="span-2" />
        <label className="checkbox span-2">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          통장 등에서 실제 입금을 확인했습니다
        </label>
        {record.isError && (
          <div className="alert alert-error span-2" role="alert">
            {messageOf(record.error)}
          </div>
        )}
      </form>
    </Dialog>
  )
}

function ReasonDialog({
  title,
  description,
  confirmLabel,
  pending,
  error,
  onConfirm,
  onClose,
}: {
  title: string
  description: string
  confirmLabel: string
  pending: boolean
  error: unknown
  onConfirm: (reason: string) => void
  onClose: () => void
}) {
  const [reason, setReason] = useState('')
  return (
    <Dialog
      open
      onClose={onClose}
      title={title}
      footer={
        <>
          <span className="spacer" />
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            닫기
          </button>
          <button type="button" className="btn btn-danger" disabled={!reason.trim() || pending} onClick={() => onConfirm(reason.trim())}>
            {confirmLabel}
          </button>
        </>
      }
    >
      <p style={{ marginTop: 0 }}>{description}</p>
      <TextField label="사유" value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} autoFocus />
      {Boolean(error) && (
        <div className="alert alert-error" role="alert" style={{ marginTop: 12 }}>
          {messageOf(error)}
        </div>
      )}
    </Dialog>
  )
}

type Modal = { kind: 'issue' } | { kind: 'payment' } | { kind: 'cancel' } | { kind: 'void'; paymentId: string } | null

/** 11 인보이스 상세 */
export function InvoiceDetailPage() {
  const { invoiceId = '' } = useParams()
  const navigate = useNavigate()
  const invoice = useInvoice(invoiceId)
  const remove = useDeleteInvoice(invoiceId)
  const cancel = useCancelInvoice(invoiceId)
  const reissue = useReissueInvoice(invoiceId)
  const voidPayment = useVoidPayment(invoiceId)
  const [modal, setModal] = useState<Modal>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const user = useOutletContext<User>()

  if (invoice.isError && invoice.error instanceof ApiError && invoice.error.status === 404) return <NotFoundPage />
  if (invoice.isPending) return <Loading />
  if (invoice.isError) return <LoadError error={invoice.error} onRetry={() => void invoice.refetch()} />

  const inv = invoice.data
  const badge = invoiceBadge(inv)
  const snap = inv.snapshot as Snapshot | null
  const paidRatio = inv.total === '0' ? 0 : Number((BigInt(inv.paid_amount) * 100n) / BigInt(inv.total))
  const activePayments = inv.payments.filter((p) => !p.voided_at)

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">
            <Link to="/invoices">인보이스</Link>
          </p>
          <h1 className="page-title">{inv.invoice_no ?? '인보이스 초안'}</h1>
          <p className="page-desc">
            <Link to={`/projects/${inv.project_id}`}>{inv.project_name}</Link> · {inv.title}
            {inv.issue_date && ` · 발행일 ${formatFullDate(inv.issue_date)}`}
          </p>
        </div>
        <div className="head-actions">
          {inv.status === 'draft' && (
            <>
              <Link to={`/invoices/${inv.id}/edit`} className="btn btn-secondary">
                초안 수정
              </Link>
              <button type="button" className="btn btn-primary" onClick={() => setModal({ kind: 'issue' })}>
                발행
              </button>
            </>
          )}
          {inv.status !== 'draft' && (
            <a className="btn btn-secondary" href={invoicePdfUrl(inv.id, true)}>
              인보이스 PDF
            </a>
          )}
          {inv.status === 'issued' && inv.balance !== '0' && (
            <button type="button" className="btn btn-primary" onClick={() => setModal({ kind: 'payment' })}>
              + 입금 기록
            </button>
          )}
        </div>
      </div>

      {inv.status === 'draft' && (!user.bank_name || !user.bank_account || !user.issuer_contact) && (
        <div className="notice notice-row" role="status" style={{ marginBottom: 20 }}>
          <p>
            발행하면 발행자 정보가 문서에 고정돼요. 입금 계좌·연락처가 비어 있으면 거래처가 입금할 곳을 알 수 없어요.{' '}
            <Link to="/settings" className="link-strong">
              설정에서 발행자 정보 입력 →
            </Link>
          </p>
        </div>
      )}
      {inv.status === 'cancelled' && (
        <div className="alert alert-error" role="status" style={{ marginBottom: 20 }}>
          {inv.cancelled_at && `${formatFullDate(localDateOf(inv.cancelled_at))}에 `}취소한 인보이스예요. 사유: {inv.cancel_reason}
          {inv.replaced_by_invoice_id && (
            <>
              {' '}
              <Link to={`/invoices/${inv.replaced_by_invoice_id}`} className="link-strong">
                재발행본 보기
              </Link>
            </>
          )}
        </div>
      )}
      {inv.replaces_invoice_id && (
        <p className="muted small" style={{ marginTop: -16 }}>
          <Link to={`/invoices/${inv.replaces_invoice_id}`}>취소된 인보이스</Link>를 다시 발행하기 위한 문서예요.
        </p>
      )}

      <div className="contract-layout">
        <DocumentPreview invoice={inv} />

        <aside className="contract-side">
          <section className="card" aria-labelledby="balance-title">
            <div className="card-head">
              <h2 id="balance-title" className="card-title">
                청구 및 입금
              </h2>
              <span className={badge.className}>{badge.label}</span>
            </div>
            <dl className="amount-list">
              <div>
                <dt>청구 금액</dt>
                <dd>{formatWon(inv.total)}</dd>
              </div>
              <div>
                <dt>누적 입금액</dt>
                <dd>{inv.status === 'draft' ? '—' : formatWon(inv.paid_amount)}</dd>
              </div>
              {inv.status === 'issued' && (
                <div className="amount-strong">
                  <dt>미수 잔액</dt>
                  <dd>{formatWon(inv.balance)}</dd>
                </div>
              )}
            </dl>
            <p className={inv.is_overdue ? 'field-error' : 'muted'}>
              지급 기한 {inv.due_date ? formatFullDate(inv.due_date) : '미정'}
              {inv.is_overdue && ' · 기한이 지났어요'}
            </p>
            {inv.status === 'issued' && (
              <>
                <ProgressBar value={paidRatio} label="입금 비율" />
                <p className="muted small">청구 금액의 {paidRatio}% 입금 확인</p>
              </>
            )}
          </section>

          {inv.status !== 'draft' && (
            <section className="card" aria-labelledby="payments-title">
              <h2 id="payments-title" className="card-title">
                입금 기록
              </h2>
              {inv.payments.length === 0 ? (
                <p className="muted" style={{ margin: 0 }}>
                  아직 기록한 입금이 없어요.
                </p>
              ) : (
                <ul className="payment-list">
                  {inv.payments.map((p) => (
                    <li key={p.id} className={p.voided_at ? 'is-voided' : undefined}>
                      <div className="between">
                        <strong>{formatWon(p.amount)}</strong>
                        <span className="muted small">{formatFullDate(p.paid_on)}</span>
                      </div>
                      <p className="muted small">
                        직접 확인 · {PAYMENT_METHOD_LABELS[p.method] ?? p.method}
                        {p.memo && ` · ${p.memo}`}
                      </p>
                      {p.voided_at ? (
                        <p className="small field-error">취소됨: {p.void_reason}</p>
                      ) : (
                        <div className="payment-actions">
                          <a className="btn btn-secondary" href={receiptPdfUrl(p.id, true)}>
                            입금확인서 PDF
                          </a>
                          <button type="button" className="btn btn-danger-text" onClick={() => setModal({ kind: 'void', paymentId: p.id })}>
                            입금 취소
                          </button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          <section className="card" aria-labelledby="basis-title">
            <h2 id="basis-title" className="card-title">
              청구 근거
            </h2>
            {snap?.contract && (
              <p className="muted small" style={{ marginTop: 0 }}>
                {snap.contract.title} · 계약 v{snap.contract.version_no}
              </p>
            )}
            <ul className="basis-list">
              {inv.items.map((item, i) => {
                const term = snap?.items[i]?.payment_term
                return (
                  <li key={item.id}>
                    <strong>{term ? `${term.requirement ? `${term.requirement} ` : ''}${term.label}` : item.description}</strong>
                    {item.basis_note && (
                      <span className={item.basis_confirmed_at ? 'basis-ok' : 'field-error'}>
                        {item.basis_confirmed_at ? '✓ ' : '확인 필요: '}
                        {item.basis_note}
                        {item.basis_confirmed_at && ` · 사용자 확인 ${formatMonthDay(localDateOf(item.basis_confirmed_at))}`}
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
          </section>

          <div className="notice">
            <p>입금확인서는 직접 확인한 입금 기록을 근거로 해요. 세금계산서 또는 법정 현금영수증이 아닙니다.</p>
          </div>

          <section className="card card-quiet">
            {inv.status === 'draft' && (
              <button
                type="button"
                className="btn btn-danger-text"
                disabled={remove.isPending}
                onClick={() => (confirmDelete ? remove.mutate(undefined, { onSuccess: () => navigate('/invoices', { replace: true }) }) : setConfirmDelete(true))}
              >
                {confirmDelete ? '정말 초안을 삭제할까요?' : '초안 삭제'}
              </button>
            )}
            {inv.status === 'issued' && (
              <button type="button" className="btn btn-danger-text" onClick={() => setModal({ kind: 'cancel' })} disabled={activePayments.length > 0}>
                인보이스 취소
              </button>
            )}
            {inv.status === 'issued' && activePayments.length > 0 && <p className="muted small">입금 기록이 있으면 먼저 입금을 취소해야 인보이스를 취소할 수 있어요.</p>}
            {inv.status === 'cancelled' && !inv.replaced_by_invoice_id && (
              <button
                type="button"
                className="btn btn-secondary"
                disabled={reissue.isPending}
                onClick={() => reissue.mutate(undefined, { onSuccess: (copy) => navigate(`/invoices/${copy.id}`) })}
              >
                같은 내용으로 재발행 초안 만들기
              </button>
            )}
            {(remove.isError || reissue.isError) && <p className="field-error">{messageOf(remove.error ?? reissue.error)}</p>}
          </section>
        </aside>
      </div>

      {modal?.kind === 'issue' && <IssueDialog invoice={inv} user={user} onClose={() => setModal(null)} />}
      {modal?.kind === 'payment' && <PaymentDialog invoice={inv} onClose={() => setModal(null)} />}
      {modal?.kind === 'cancel' && (
        <ReasonDialog
          title="인보이스 취소"
          description="취소한 인보이스는 기록으로 남고, 같은 지급 단계를 다시 청구할 수 있게 돼요."
          confirmLabel="인보이스 취소"
          pending={cancel.isPending}
          error={cancel.error}
          onConfirm={(reason) => cancel.mutate(reason, { onSuccess: () => setModal(null) })}
          onClose={() => setModal(null)}
        />
      )}
      {modal?.kind === 'void' && (
        <ReasonDialog
          title="입금 기록 취소"
          description="잘못 기록한 입금은 지우지 않고 취소 이력으로 남겨요. 이 입금으로 만든 입금확인서는 무효가 돼요."
          confirmLabel="입금 취소"
          pending={voidPayment.isPending}
          error={voidPayment.error}
          onConfirm={(reason) => voidPayment.mutate({ paymentId: modal.paymentId, reason }, { onSuccess: () => setModal(null) })}
          onClose={() => setModal(null)}
        />
      )}
    </>
  )
}
