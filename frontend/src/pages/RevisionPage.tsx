import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import { useContract } from '../api/contracts'
import { messageOf } from '../api/messages'
import { useProject } from '../api/projects'
import { useReviseContract, useRevisionDraft, type RevisionDraft } from '../api/revision'
import { AmountField } from '../components/AmountField'
import { TextField } from '../components/Field'
import { EmptyState, LoadError, Loading } from '../components/ui'
import { formatFullDate, formatWon } from '../lib/format'
import { newIdempotencyKey } from '../lib/idempotency'

const STAGE_OPTIONS = [
  { value: 'deposit', label: '선금' },
  { value: 'interim', label: '중도금' },
  { value: 'balance', label: '잔금' },
  { value: 'other', label: '기타' },
] as const

type Stage = (typeof STAGE_OPTIONS)[number]['value']
type Term = { key: string; stage: Stage; label: string; amount: string; requirement: string }

const won = (v: string) => BigInt(v || '0')

function Change({ label, from, to }: { label: string; from: string; to: string }) {
  const changed = from !== to
  return (
    <div className="revision-change">
      <span className="muted small">{label}</span>
      <strong>
        {changed ? (
          <>
            <span className="muted is-old">{from}</span> → {to}
          </>
        ) : (
          to
        )}
      </strong>
    </div>
  )
}

function RevisionForm({ projectId, draft }: { projectId: string; draft: RevisionDraft }) {
  const navigate = useNavigate()
  const revise = useReviseContract(projectId)
  const [idempotencyKey] = useState(newIdempotencyKey)
  const [amount, setAmount] = useState(draft.to_version.contract_amount)
  const [dueDate, setDueDate] = useState(draft.to_version.due_date ?? '')
  const [terms, setTerms] = useState<Term[]>(() =>
    draft.new_terms.map((t) => ({ key: t.key, stage: t.stage, label: t.label, amount: t.amount, requirement: t.requirement ?? '' })),
  )
  const [carry, setCarry] = useState<Record<string, string>>(() =>
    Object.fromEntries(draft.proposed_carry.map((c) => [c.from_term_id, c.to_key])),
  )
  const [nextKey, setNextKey] = useState(1)
  const [checked, setChecked] = useState(false)

  const billedOld = draft.old_terms.filter((o) => o.must_carry)
  const unbilledOld = draft.old_terms.filter((o) => !o.must_carry)
  const need = (o: (typeof billedOld)[number]) => won(o.billed) + won(o.drafted)

  // 새 단계마다 이어 붙는 금액
  const load = new Map<string, bigint>()
  for (const o of billedOld) {
    const key = carry[o.term_id]
    if (key) load.set(key, (load.get(key) ?? 0n) + need(o))
  }
  const termsTotal = terms.reduce((sum, t) => sum + won(t.amount), 0n)
  const carriedTotal = billedOld.reduce((sum, o) => sum + need(o), 0n)
  const problems: string[] = []
  if (termsTotal !== won(amount)) problems.push(`단계 합계 ${formatWon(termsTotal.toString())}가 계약 금액 ${formatWon(amount || '0')}와 달라요.`)
  if (carriedTotal > won(amount)) problems.push('새 계약 금액이 이미 청구한 금액보다 적어요. 청구를 취소·재발행해 맞춘 뒤 반영해 주세요.')
  for (const o of billedOld) if (!carry[o.term_id] || !terms.some((t) => t.key === carry[o.term_id])) problems.push(`'${o.label}'을 이어 붙일 새 단계를 골라 주세요.`)
  for (const t of terms) if ((load.get(t.key) ?? 0n) > won(t.amount)) problems.push(`'${t.label || '새 단계'}'에 이어 붙인 청구액이 단계 금액보다 커요.`)
  for (const t of terms) if (!t.label.trim() || !t.amount) problems.push('모든 단계에 이름과 금액을 입력해 주세요.')
  const uniqueProblems = [...new Set(problems)]
  const valid = uniqueProblems.length === 0 && checked

  const setTerm = (i: number, patch: Partial<Term>) => setTerms((ts) => ts.map((t, j) => (j === i ? { ...t, ...patch } : t)))
  const removeTerm = (i: number) => {
    const key = terms[i]?.key
    setTerms((ts) => ts.filter((_, j) => j !== i))
    setCarry((c) => Object.fromEntries(Object.entries(c).filter(([, k]) => k !== key)))
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    revise.mutate(
      {
        idempotencyKey,
        body: {
          contract_version_id: draft.to_version.id,
          version: draft.project_version,
          contract_amount: amount || '0',
          due_date: dueDate || null,
          payment_terms: terms.map((t) => ({
            key: t.key,
            stage: t.stage,
            label: t.label.trim(),
            amount: t.amount,
            requirement: t.requirement.trim() || null,
          })),
          carry: billedOld.map((o) => ({ from_term_id: o.term_id, to_key: carry[o.term_id]! })),
        },
      },
      { onSuccess: () => navigate(`/projects/${projectId}`, { replace: true }) },
    )
  }

  const termOptions = terms.map((t) => ({ value: t.key, label: `${t.label || '새 단계'} · ${formatWon(t.amount || '0')}` }))

  return (
    <form onSubmit={onSubmit} noValidate>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">
            <Link to={`/projects/${projectId}`}>프로젝트</Link> / 수정 계약 반영
          </p>
          <h1 className="page-title">수정 계약 반영</h1>
          <p className="page-desc">
            {draft.contract_title} · v{draft.from_version.version_no} → v{draft.to_version.version_no}. 이미 청구한 기록은 그대로 두고, 새 지급 단계로
            이어 붙여요.
          </p>
        </div>
        <div className="head-actions">
          <Link to={`/projects/${projectId}`} className="btn btn-secondary">
            취소
          </Link>
          <button type="submit" className="btn btn-primary" disabled={!valid || revise.isPending}>
            {revise.isPending ? '반영 중…' : '수정 계약 반영'}
          </button>
        </div>
      </div>

      <div className="summary-bar revision-summary">
        <Change label="계약 금액" from={formatWon(draft.from_version.contract_amount)} to={formatWon(amount || '0')} />
        <Change
          label="최종 납기"
          from={draft.from_version.due_date ? formatFullDate(draft.from_version.due_date) : '미정'}
          to={dueDate ? formatFullDate(dueDate) : '미정'}
        />
        <Change label="지급 단계" from={`${draft.old_terms.length}개`} to={`${terms.length}개`} />
        <Change label="이미 청구" from={formatWon(carriedTotal.toString())} to={formatWon(carriedTotal.toString())} />
      </div>

      {revise.isError && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 20 }}>
          {messageOf(revise.error)}
        </div>
      )}

      <div className="grid-2 revision-grid">
        <section className="card" aria-labelledby="old-title">
          <h2 id="old-title" className="card-title">
            이미 청구한 단계 (v{draft.from_version.version_no})
          </h2>
          {billedOld.length === 0 ? (
            <p className="muted">청구한 단계가 없어요. 새 단계로 그대로 바뀌어요.</p>
          ) : (
            <ul className="row-list">
              {billedOld.map((o) => (
                <li key={o.term_id} className="carry-row">
                  <div>
                    <strong>
                      {o.label} · {formatWon(o.amount)}
                    </strong>
                    <span className="muted small">
                      청구 {formatWon(o.billed)}
                      {o.drafted !== '0' && ` · 초안 ${formatWon(o.drafted)} (새 단계로 옮겨져요)`}
                    </span>
                    <span className="small">
                      {o.invoices.map((inv, i) => (
                        <span key={inv.id}>
                          {i > 0 && ', '}
                          <Link to={`/invoices/${inv.id}`} className="muted-link">
                            {inv.invoice_no ?? '초안'}
                          </Link>
                        </span>
                      ))}
                    </span>
                  </div>
                  <label className="field carry-select">
                    <span className="field-label">이어 붙일 새 단계</span>
                    <select
                      className="input"
                      value={carry[o.term_id] ?? ''}
                      onChange={(e) => setCarry((c) => ({ ...c, [o.term_id]: e.target.value }))}
                    >
                      <option value="">골라 주세요</option>
                      {termOptions.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </li>
              ))}
            </ul>
          )}
          {unbilledOld.length > 0 && (
            <p className="muted small" style={{ marginBottom: 0 }}>
              청구한 적 없는 {unbilledOld.map((o) => o.label).join(', ')}은(는) 새 단계로 대체돼요.
            </p>
          )}
        </section>

        <section className="card" aria-labelledby="new-title">
          <h2 id="new-title" className="card-title">
            새 지급 단계 (v{draft.to_version.version_no})
          </h2>
          {draft.payment_terms_text && <p className="muted small">계약서: {draft.payment_terms_text}</p>}
          <div className="form-grid">
            <AmountField label="계약 금액" value={amount} onChange={setAmount} />
            <TextField label="최종 납기" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          </div>
          <ul className="term-rows">
            {terms.map((t, i) => {
              const carried = load.get(t.key) ?? 0n
              const left = won(t.amount) - carried
              return (
                <li key={t.key}>
                  <div className="term-row-head">
                    <select
                      className="input input-sm"
                      aria-label="지급 단계"
                      value={t.stage}
                      onChange={(e) => setTerm(i, { stage: e.target.value as Stage })}
                    >
                      {STAGE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    <input
                      className="input input-sm"
                      aria-label="단계 이름"
                      value={t.label}
                      maxLength={50}
                      onChange={(e) => setTerm(i, { label: e.target.value })}
                    />
                    {terms.length > 1 && (
                      <button type="button" className="icon-button" aria-label="단계 삭제" onClick={() => removeTerm(i)}>
                        ×
                      </button>
                    )}
                  </div>
                  <AmountField label="금액" value={t.amount} onChange={(v) => setTerm(i, { amount: v })} />
                  <TextField
                    label="지급 요건"
                    value={t.requirement}
                    maxLength={200}
                    onChange={(e) => setTerm(i, { requirement: e.target.value })}
                  />
                  <p className={left < 0n ? 'field-error' : 'field-hint'} style={{ margin: 0 }}>
                    이전 계약에서 이월 {formatWon(carried.toString())} · 앞으로 청구 가능 {formatWon((left < 0n ? 0n : left).toString())}
                  </p>
                </li>
              )
            })}
          </ul>
          <button
            type="button"
            className="link-button"
            onClick={() => {
              setTerms((ts) => [...ts, { key: `n${nextKey}`, stage: 'other', label: '', amount: '', requirement: '' }])
              setNextKey((k) => k + 1)
            }}
          >
            + 단계 추가
          </button>
        </section>
      </div>

      {uniqueProblems.length > 0 && (
        <ul className="alert alert-error revision-problems" role="status">
          {uniqueProblems.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}

      <div className="notice" style={{ marginTop: 20 }}>
        <p>
          발행한 인보이스와 입금확인서는 바뀌지 않아요. 이월된 금액만큼은 새 단계에서 다시 청구할 수 없고, 옛 인보이스를 취소하면 그만큼 다시 청구할 수 있어요.
        </p>
      </div>
      <label className="checkbox" style={{ marginTop: 14 }}>
        <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
        바뀌는 금액·납기·지급 단계와 이어 붙일 단계를 확인했습니다
      </label>
    </form>
  )
}

/** 수정 계약 반영: 청구 이력을 새 계약 버전의 지급 단계로 이어 붙인다 */
export function RevisionPage() {
  const { projectId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const project = useProject(projectId)
  const contractId = project.data?.contract_id ?? ''
  const contract = useContract(contractId)
  // 주소에 버전이 없으면 계약의 최신 버전을 반영한다
  const versionId = searchParams.get('version') ?? (contract.data ? contract.data.version_id : null)
  const draft = useRevisionDraft(projectId, versionId)

  if (project.isPending || (contractId && contract.isPending)) return <Loading />
  if (project.isError) return <LoadError error={project.error} onRetry={() => void project.refetch()} />
  if (!contractId) {
    return (
      <EmptyState title="계약서가 연결되지 않은 프로젝트예요.">
        <Link to={`/projects/${projectId}`} className="btn btn-secondary">
          프로젝트로 돌아가기
        </Link>
      </EmptyState>
    )
  }
  if (draft.isPending) return <Loading />
  if (draft.isError) {
    return (
      <div className="center-block">
        <p>{messageOf(draft.error)}</p>
        <Link to={contractId ? `/contracts/${contractId}` : `/projects/${projectId}`} className="btn btn-secondary">
          {contractId ? '계약서 확인하러 가기' : '프로젝트로 돌아가기'}
        </Link>
      </div>
    )
  }
  return <RevisionForm projectId={projectId} draft={draft.data} />
}
