import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import { messageOf } from '../api/messages'
import {
  useBillingCandidates,
  useInvoice,
  useSaveInvoice,
  type BillingCandidates,
  type InvoiceDetail,
  type InvoiceItemInput,
} from '../api/invoices'
import { useProjects } from '../api/projects'
import { AmountField } from '../components/AmountField'
import { SelectField, TextField } from '../components/Field'
import { EmptyState, LoadError, Loading } from '../components/ui'
import { formatWon, groupDigits } from '../lib/format'

type StagePick = { checked: boolean; amount: string; basisNote: string; basisConfirmed: boolean }
type ExtraRow = { description: string; detail: string; amount: string }

/** 시간 × 단가를 정수 연산으로 원 단위 반올림 (서버와 같은 규칙, 미리보기용) */
function hourlyAmount(hours: string, rate: string): bigint {
  const [whole = '0', frac = ''] = hours.split('.')
  const hundredths = BigInt(whole) * 100n + BigInt((frac + '00').slice(0, 2))
  return (hundredths * BigInt(rate) + 50n) / 100n
}

const big = (v: string) => BigInt(v || '0')

function InvoiceForm({
  projectId,
  candidates,
  initial,
  projectName,
}: {
  projectId: string
  candidates: BillingCandidates
  initial?: InvoiceDetail
  projectName?: string
}) {
  const navigate = useNavigate()
  const save = useSaveInvoice(initial?.id)
  const items = initial?.items ?? []

  // 제목을 직접 고치기 전에는 고른 항목으로 자동 제안한다 (UX 문서 4장 A)
  const [manualTitle, setManualTitle] = useState<string | null>(initial?.title ?? null)
  const [dueDate, setDueDate] = useState(initial?.due_date ?? '')
  const [stages, setStages] = useState<Record<string, StagePick>>(() =>
    Object.fromEntries(
      candidates.payment_terms.map((t) => {
        const existing = items.find((i) => i.kind === 'payment_stage' && i.payment_term_id === t.payment_term_id)
        return [
          t.payment_term_id,
          {
            checked: Boolean(existing),
            amount: existing?.unit_price ?? (t.remaining_amount === '0' ? '' : t.remaining_amount),
            basisNote: existing?.basis_note ?? (t.requirement ? `${t.requirement.replace(/\s*후$/, '')} 확인` : ''),
            basisConfirmed: Boolean(existing?.basis_confirmed_at),
          },
        ]
      }),
    ),
  )
  const hourlyTasks = candidates.tasks.filter((t) => t.hours !== null && t.hourly_rate !== null)
  const [hourly, setHourly] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(hourlyTasks.map((t) => [t.task_id, items.some((i) => i.kind === 'hourly' && i.task_id === t.task_id)])),
  )
  const [extras, setExtras] = useState<ExtraRow[]>(() =>
    items.filter((i) => i.kind === 'extra' || i.kind === 'task').map((i) => ({ description: i.description, detail: i.detail ?? '', amount: i.unit_price })),
  )
  const [showTax, setShowTax] = useState(Boolean(initial && (initial.tax_amount !== '0' || initial.withholding_amount !== '0')))
  const [tax, setTax] = useState(initial?.tax_amount === '0' ? '' : (initial?.tax_amount ?? ''))
  const [withholding, setWithholding] = useState(initial?.withholding_amount === '0' ? '' : (initial?.withholding_amount ?? ''))
  const [adjustmentNote, setAdjustmentNote] = useState(initial?.adjustment_note ?? '')

  const setStage = (id: string, patch: Partial<StagePick>) => setStages((s) => ({ ...s, [id]: { ...s[id]!, ...patch } }))
  const setExtra = (i: number, patch: Partial<ExtraRow>) => setExtras((rows) => rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))

  const pickedStages = candidates.payment_terms.filter((t) => stages[t.payment_term_id]?.checked)
  const pickedHourly = hourlyTasks.filter((t) => hourly[t.task_id])
  const validExtras = extras.filter((r) => r.description.trim() && r.amount)

  const suggestedTitle = (() => {
    const parts: string[] = []
    if (pickedStages.length > 0) parts.push(pickedStages.map((t) => t.label).join(' + '))
    if (pickedHourly.length > 0) parts.push(`시간제 ${pickedHourly.length}건`)
    if (validExtras.length > 0) parts.push(`추가 작업 ${validExtras.length}건`)
    const core = parts.join(' · ')
    return (core ? (projectName ? `${projectName} ${core}` : core) : '').slice(0, 100)
  })()
  const title = manualTitle ?? suggestedTitle
  const titleAuto = manualTitle === null

  const subtotal =
    pickedStages.reduce((s, t) => s + big(stages[t.payment_term_id]!.amount), 0n) +
    pickedHourly.reduce((s, t) => s + hourlyAmount(t.hours!, t.hourly_rate!), 0n) +
    validExtras.reduce((s, r) => s + big(r.amount), 0n)
  const total = subtotal + big(tax) - big(withholding)

  const overLimit = pickedStages.filter((t) => big(stages[t.payment_term_id]!.amount) > big(t.remaining_amount))
  const itemCount = pickedStages.length + pickedHourly.length + validExtras.length
  const valid = title.trim() !== '' && itemCount > 0 && total >= 0n && overLimit.length === 0 && pickedStages.every((t) => stages[t.payment_term_id]!.amount)

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    const body: InvoiceItemInput[] = [
      ...pickedStages.map((t) => {
        const pick = stages[t.payment_term_id]!
        return {
          kind: 'payment_stage' as const,
          description: `${t.label} 청구`,
          quantity: '1',
          unit_price: pick.amount,
          payment_term_id: t.payment_term_id,
          basis_note: pick.basisNote.trim() || null,
          basis_confirmed: pick.basisConfirmed,
        }
      }),
      ...pickedHourly.map((t) => ({
        kind: 'hourly' as const,
        description: t.title,
        quantity: t.hours!,
        basis_confirmed: false,
        detail: `확인된 작업 시간 ${t.hours}시간`,
        unit_price: t.hourly_rate!,
        task_id: t.task_id,
      })),
      ...validExtras.map((r) => ({
        kind: 'extra' as const,
        description: r.description.trim(),
        quantity: '1',
        detail: r.detail.trim() || null,
        unit_price: r.amount,
        basis_note: '합의한 추가 작업',
        basis_confirmed: true,
      })),
    ]
    save.mutate(
      {
        project_id: projectId,
        title: title.trim(),
        due_date: dueDate || null,
        items: body,
        tax_amount: tax || '0',
        withholding_amount: withholding || '0',
        adjustment_note: adjustmentNote.trim() || null,
        ...(initial ? { version: initial.version } : {}),
      },
      { onSuccess: (inv) => navigate(`/invoices/${inv.id}`, { replace: true }) },
    )
  }

  return (
    <form onSubmit={onSubmit} noValidate className="contract-layout">
      <div className="stack">
        <section className="card" aria-labelledby="stage-title">
          <h2 id="stage-title" className="card-title">
            계약 지급 단계
          </h2>
          {candidates.payment_terms.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              계약서로 만든 프로젝트가 아니라 지급 단계가 없어요. 아래 추가 항목으로 청구하거나, 계약서에서 프로젝트를 만들어 주세요.
            </p>
          ) : (
            <ul className="pick-list">
              {candidates.payment_terms.map((t) => {
                const pick = stages[t.payment_term_id]!
                const done = t.remaining_amount === '0'
                return (
                  <li key={t.payment_term_id} className={pick.checked ? 'is-picked' : undefined}>
                    <label className="checkbox pick-head">
                      <input
                        type="checkbox"
                        checked={pick.checked}
                        disabled={done && !pick.checked}
                        onChange={(e) => setStage(t.payment_term_id, { checked: e.target.checked })}
                      />
                      <strong>{t.label}</strong>
                      <span className="muted">
                        {formatWon(t.amount)} · 청구됨 {formatWon(t.billed_amount)} · 남은 금액 {formatWon(t.remaining_amount)}
                      </span>
                      {done && <span className="badge badge-green">청구 완료</span>}
                    </label>
                    {t.drafted_amount !== '0' && !initial && (
                      <p className="field-hint">다른 초안에 {formatWon(t.drafted_amount)}이 잡혀 있어요. 발행할 때 한도를 다시 확인해요.</p>
                    )}
                    {pick.checked && (
                      <div className="pick-body">
                        <AmountField
                          label="청구 금액"
                          value={pick.amount}
                          onChange={(v) => setStage(t.payment_term_id, { amount: v })}
                          error={big(pick.amount) > big(t.remaining_amount) ? `남은 금액 ${formatWon(t.remaining_amount)}을 넘을 수 없어요.` : undefined}
                        />
                        {t.requirement && (
                          <div className="requirement">
                            <p className="small">
                              지급 요건: <strong>{t.requirement}</strong>
                            </p>
                            <TextField
                              label="확인한 내용"
                              value={pick.basisNote}
                              maxLength={200}
                              onChange={(e) => setStage(t.payment_term_id, { basisNote: e.target.value })}
                            />
                            <label className="checkbox">
                              <input
                                type="checkbox"
                                checked={pick.basisConfirmed}
                                onChange={(e) => setStage(t.payment_term_id, { basisConfirmed: e.target.checked })}
                              />
                              지급 요건을 충족했음을 확인했습니다 (발행 전 필수)
                            </label>
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        {hourlyTasks.length > 0 && (
          <section className="card" aria-labelledby="hourly-title">
            <h2 id="hourly-title" className="card-title">
              시간제 작업
            </h2>
            <ul className="pick-list">
              {hourlyTasks.map((t) => (
                <li key={t.task_id}>
                  <label className="checkbox pick-head">
                    <input type="checkbox" checked={hourly[t.task_id] ?? false} onChange={(e) => setHourly((h) => ({ ...h, [t.task_id]: e.target.checked }))} />
                    <strong>{t.title}</strong>
                    <span className="muted">
                      {t.hours}시간 × {formatWon(t.hourly_rate)} = {formatWon(hourlyAmount(t.hours!, t.hourly_rate!).toString())}
                      {t.billed_amount !== '0' && ` · 청구됨 ${formatWon(t.billed_amount)}`}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="card" aria-labelledby="extra-title">
          <div className="card-head">
            <h2 id="extra-title" className="card-title">
              추가 작업
            </h2>
            <button type="button" className="link-button" onClick={() => setExtras((r) => [...r, { description: '', detail: '', amount: '' }])}>
              + 항목 추가
            </button>
          </div>
          {extras.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              거래처와 금액을 합의한 추가 작업만 넣어 주세요.
            </p>
          ) : (
            <ul className="edit-rows">
              {extras.map((r, i) => (
                <li key={i}>
                  <input className="input" aria-label="항목" placeholder="항목 (예: 배너 2종 추가)" value={r.description} maxLength={200} onChange={(e) => setExtra(i, { description: e.target.value })} />
                  <input
                    className="input input-sm"
                    aria-label="금액"
                    inputMode="numeric"
                    placeholder="금액"
                    value={r.amount ? groupDigits(r.amount) : ''}
                    onChange={(e) => setExtra(i, { amount: e.target.value.replace(/\D/g, '').replace(/^0+(?=\d)/, '').slice(0, 14) })}
                  />
                  <button type="button" className="icon-button" aria-label="항목 삭제" onClick={() => setExtras((rows) => rows.filter((_, j) => j !== i))}>
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <aside className="contract-side">
        <section className="card" aria-labelledby="summary-title">
          <h2 id="summary-title" className="card-title">
            청구 내용
          </h2>
          <div className="stack-sm">
            <TextField
              label="제목"
              placeholder="예: 디자인 잔금"
              value={title}
              onChange={(e) => setManualTitle(e.target.value)}
              maxLength={100}
              hint={titleAuto && suggestedTitle ? '고른 항목으로 자동으로 지었어요. 직접 바꿀 수 있어요.' : undefined}
            />
            <TextField label="지급 기한" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} hint="발행할 때 필요해요." />
            {showTax ? (
              <>
                <AmountField label="세액" value={tax} onChange={setTax} />
                <AmountField label="원천징수" value={withholding} onChange={setWithholding} />
                <TextField label="조정 근거" placeholder="예: 사업소득 3.3% 원천징수" value={adjustmentNote} maxLength={300} onChange={(e) => setAdjustmentNote(e.target.value)} />
              </>
            ) : (
              <button type="button" className="link-button" onClick={() => setShowTax(true)}>
                + 세액·원천징수 입력
              </button>
            )}
          </div>
          <dl className="money-box" style={{ marginTop: 20 }}>
            <div>
              <dt>항목 합계</dt>
              <dd>{formatWon(subtotal.toString())}</dd>
            </div>
            {showTax && (
              <div>
                <dt>세액 − 원천징수</dt>
                <dd>{formatWon((big(tax) - big(withholding)).toString())}</dd>
              </div>
            )}
            <div>
              <dt>총 청구 금액</dt>
              <dd className="total-amount">{formatWon(total.toString())}</dd>
            </div>
          </dl>
          <p className="field-hint" style={{ margin: '0 0 12px' }}>
            저장할 때 서버가 금액을 다시 계산해요. 초안은 미수액에 포함되지 않아요.
          </p>
          {save.isError && (
            <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
              {messageOf(save.error)}
            </div>
          )}
          <button type="submit" className="btn btn-primary btn-block" disabled={!valid || save.isPending}>
            {save.isPending ? '저장 중…' : '초안 저장'}
          </button>
          {itemCount === 0 && <p className="field-hint">청구할 항목을 하나 이상 골라 주세요.</p>}
        </section>
      </aside>
    </form>
  )
}

/** 인보이스 작성(/invoices/new?project=)과 초안 수정(/invoices/:id/edit) */
export function InvoiceFormPage() {
  const { invoiceId } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const existing = useInvoice(invoiceId ?? '')
  const projects = useProjects('all')
  const editing = Boolean(invoiceId)
  const projectId = editing ? (existing.data?.project_id ?? null) : searchParams.get('project')
  const candidates = useBillingCandidates(projectId)
  const projectName = projects.data?.items.find((p) => p.id === projectId)?.name

  if (editing && existing.isPending) return <Loading />
  if (editing && existing.isError) return <LoadError error={existing.error} onRetry={() => void existing.refetch()} />
  if (editing && existing.data && existing.data.status !== 'draft') {
    return (
      <div className="center-block">
        <p>발행된 인보이스는 고칠 수 없어요. 취소한 뒤 재발행해 주세요.</p>
        <Link to={`/invoices/${invoiceId}`} className="btn btn-secondary">
          인보이스로 돌아가기
        </Link>
      </div>
    )
  }

  const projectOptions = (projects.data?.items ?? [])
    .filter((p) => p.status !== 'archived' || p.id === projectId)
    .map((p) => ({ value: p.id, label: `${p.name} · ${p.client.name}` }))

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">
            <Link to="/invoices">인보이스</Link> / {editing ? '초안 수정' : '작성'}
          </p>
          <h1 className="page-title">{editing ? '인보이스 초안 수정' : '인보이스 작성'}</h1>
          <p className="page-desc">계약 지급 조건과 완료 작업을 대조해 청구 항목을 고르세요.</p>
        </div>
      </div>

      {!editing && (
        <section className="card" style={{ marginBottom: 24 }}>
          {projects.isPending ? (
            <Loading />
          ) : projectOptions.length === 0 ? (
            <EmptyState title="먼저 프로젝트를 만들어 주세요.">
              <Link to="/projects" className="btn btn-secondary">
                프로젝트로 가기
              </Link>
            </EmptyState>
          ) : (
            <SelectField
              label="청구할 프로젝트"
              options={[{ value: '', label: '프로젝트를 선택하세요' }, ...projectOptions]}
              value={projectId ?? ''}
              onChange={(e) => setSearchParams(e.target.value ? { project: e.target.value } : {}, { replace: true })}
            />
          )}
        </section>
      )}

      {projectId &&
        (candidates.isPending ? (
          <Loading />
        ) : candidates.isError ? (
          <LoadError error={candidates.error} onRetry={() => void candidates.refetch()} />
        ) : (
          <InvoiceForm
            key={projectId}
            projectId={projectId}
            candidates={candidates.data}
            initial={existing.data}
            projectName={projectName}
          />
        ))}
    </>
  )
}
