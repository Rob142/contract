import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import type { JobType } from '../api/auth'
import { ApiError } from '../api/client'
import { useCreateProjectFromContract, useProjectDraft, type ProjectDraft } from '../api/invoices'
import { messageOf } from '../api/messages'
import { useClients, useProjects } from '../api/projects'
import { AmountField } from '../components/AmountField'
import { SelectField, TextField } from '../components/Field'
import { LoadError, Loading } from '../components/ui'
import { formatWon, JOB_TYPE_LABELS } from '../lib/format'
import { newIdempotencyKey } from '../lib/idempotency'
import { forgetLinkTarget, recallLinkTarget } from '../lib/linkTarget'

const NEW_CLIENT = '__new__'
const JOB_OPTIONS = Object.entries(JOB_TYPE_LABELS).map(([value, label]) => ({ value, label }))
const STAGE_OPTIONS = [
  { value: 'deposit', label: '선금' },
  { value: 'interim', label: '중도금' },
  { value: 'balance', label: '잔금' },
  { value: 'other', label: '기타' },
]

type Term = { stage: string; label: string; amount: string; requirement: string }
type TaskRow = { title: string; label: string; due_date: string }

const NEW_PROJECT = ''

function ProjectDraftForm({ contractId, draft, initialProjectId }: { contractId: string; draft: ProjectDraft; initialProjectId: string }) {
  const navigate = useNavigate()
  const clients = useClients()
  const projects = useProjects('all')
  // 계약서가 없는 프로젝트는 연결, 있는 프로젝트는 교체 (청구 전일 때만 서버가 허용)
  const linkable = (projects.data?.items ?? []).filter((p) => p.status !== 'archived')
  const [targetId, setTargetId] = useState(initialProjectId)
  const target = linkable.find((p) => p.id === targetId)
  const linking = Boolean(target)
  const replacing = Boolean(target?.has_contract)
  const create = useCreateProjectFromContract(contractId)
  // 재전송 키는 화면을 여는 동안 하나: 응답을 못 받아 다시 눌러도 프로젝트는 하나만 생긴다
  const [idempotencyKey] = useState(newIdempotencyKey)

  const [name, setName] = useState(draft.name)
  const [clientChoice, setClientChoice] = useState(draft.client_id ?? NEW_CLIENT)
  const [newClientName, setNewClientName] = useState('')
  const [jobType, setJobType] = useState<JobType>(draft.job_type)
  const [startDate, setStartDate] = useState(draft.start_date ?? '')
  const [dueDate, setDueDate] = useState(draft.due_date ?? '')
  const [amount, setAmount] = useState(draft.contract_amount === '0' ? '' : draft.contract_amount)
  const [terms, setTerms] = useState<Term[]>(() =>
    draft.payment_terms.map((t) => ({ stage: t.stage, label: t.label, amount: t.amount, requirement: t.requirement ?? '' })),
  )
  const [tasks, setTasks] = useState<TaskRow[]>(() => draft.tasks.map((t) => ({ title: t.title, label: t.label ?? '', due_date: t.due_date ?? '' })))
  const [termsChecked, setTermsChecked] = useState(false)

  const termsTotal = terms.reduce((sum, t) => sum + BigInt(t.amount || '0'), 0n)
  const totalMatches = termsTotal === BigInt(amount || '0')
  const clientOk = linking || clientChoice !== NEW_CLIENT || newClientName.trim() !== ''

  // 프로젝트 화면에서 넘어온 경우: 목록을 받은 뒤 한 번만 그 프로젝트 값으로 채운다
  const [prefilled, setPrefilled] = useState(!initialProjectId)
  if (!prefilled && projects.isSuccess) {
    setPrefilled(true)
    if (target) {
      setName(target.name)
      if (startFits(target.start_date)) setStartDate(target.start_date!)
      if (!draft.due_date && target.due_date) setDueDate(target.due_date)
    }
  }

  // 프로젝트 시작일이 계약 납기보다 늦으면 가져오지 않는다 (그대로 두면 저장할 수 없는 조합이 된다)
  function startFits(start: string | null | undefined) {
    return Boolean(start) && (!draft.due_date || start! <= draft.due_date)
  }

  const chooseTarget = (id: string) => {
    setTargetId(id)
    const p = linkable.find((x) => x.id === id)
    // 연결할 때는 프로젝트의 이름·일정을 기본값으로, 계약에 납기가 있으면 그것을 쓴다
    setName(p ? p.name : draft.name)
    if (p && startFits(p.start_date)) setStartDate(p.start_date!)
    if (p && !draft.due_date && p.due_date) setDueDate(p.due_date)
  }
  const termsOk = terms.length > 0 && terms.every((t) => t.label.trim() && t.amount)
  const datesOk = !startDate || !dueDate || dueDate >= startDate
  // 버튼이 왜 안 눌리는지 바로 보이게 한다
  const problems = [
    !name.trim() && '프로젝트명을 입력해 주세요.',
    !clientOk && '거래처 이름을 입력해 주세요.',
    !datesOk && `최종 납기(${dueDate})가 시작일(${startDate})보다 빨라요. 둘 중 하나를 고쳐 주세요.`,
    !termsOk && '지급 단계마다 이름과 금액을 입력해 주세요.',
    termsOk && !totalMatches && '지급 단계 금액의 합이 계약 금액과 같아야 해요.',
    !termsChecked && "오른쪽 아래 '지급 조건을 확인했습니다'에 체크해 주세요.",
  ].filter((x): x is string => Boolean(x))
  const valid = problems.length === 0

  const setTerm = (i: number, patch: Partial<Term>) => setTerms((ts) => ts.map((t, j) => (j === i ? { ...t, ...patch } : t)))
  const setTask = (i: number, patch: Partial<TaskRow>) => setTasks((ts) => ts.map((t, j) => (j === i ? { ...t, ...patch } : t)))

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!valid) return
    create.mutate(
      {
        idempotencyKey,
        body: {
          name: name.trim(),
          replace_contract: replacing,
          ...(linking
            ? { project_id: target!.id }
            : clientChoice === NEW_CLIENT
              ? { new_client_name: newClientName.trim() }
              : { client_id: clientChoice }),
          job_type: jobType,
          start_date: startDate || null,
          due_date: dueDate || null,
          contract_amount: amount || '0',
          payment_terms: terms.map((t) => ({
            stage: t.stage as 'deposit',
            label: t.label.trim(),
            amount: t.amount,
            requirement: t.requirement.trim() || null,
          })),
          tasks: tasks
            .filter((t) => t.title.trim())
            .map((t) => ({ title: t.title.trim(), label: t.label.trim() || null, due_date: t.due_date || null })),
        },
      },
      {
        onSuccess: (project) => {
          forgetLinkTarget(contractId)
          navigate(`/projects/${project.id}`, { replace: true })
        },
      },
    )
  }

  const clientOptions = [...(clients.data ?? []).map((c) => ({ value: c.id, label: c.name })), { value: NEW_CLIENT, label: '+ 새 거래처 입력' }]

  return (
    <form onSubmit={onSubmit} noValidate>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">
            <Link to={`/contracts/${contractId}`}>계약서</Link> / {linking ? '프로젝트에 연결' : '프로젝트 만들기'}
          </p>
          <h1 className="page-title">
            {replacing ? '프로젝트의 계약서 교체' : linking ? '기존 프로젝트에 계약 연결' : '계약 정보로 프로젝트 만들기'}
          </h1>
          <p className="page-desc">
            {linking
              ? '프로젝트의 작업은 그대로 두고, 확인한 계약 조건(금액·납기·지급 단계)을 붙여요.'
              : '확인한 계약 조건으로 만든 초안이에요. 확인하고 수정한 뒤 프로젝트를 생성하세요.'}
          </p>
        </div>
        <div className="head-actions">
          <Link to={`/contracts/${contractId}`} className="btn btn-secondary">
            취소
          </Link>
          <button type="submit" className="btn btn-primary" disabled={!valid || create.isPending}>
            {create.isPending
              ? '저장 중…'
              : replacing
                ? '확인하고 계약서 교체'
                : linking
                  ? '확인하고 프로젝트에 연결'
                  : '확인하고 프로젝트 생성'}
          </button>
        </div>
      </div>

      <ol className="stepper" aria-label="진행 단계">
        <li className="done">1 계약 확인</li>
        <li className="current" aria-current="step">
          2 프로젝트 초안 확인
        </li>
        <li>3 프로젝트 시작</li>
      </ol>

      {problems.length > 0 && (
        <div className="notice form-problems" role="status" style={{ marginBottom: 20 }}>
          <p>
            <strong>저장하려면 {problems.length}가지를 확인해 주세요</strong>
          </p>
          <ul>
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}

      {create.isError && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 20 }}>
          {messageOf(create.error)}
          {create.error instanceof ApiError && create.error.code === 'terms_total_mismatch' && ' 지급 조건의 금액을 확인해 주세요.'}
        </div>
      )}

      <div className="contract-layout">
        <div className="stack">
          <section className="card" aria-labelledby="basic-title">
            <h2 id="basic-title" className="card-title">
              기본 정보
            </h2>
            {linkable.length > 0 && (
              <SelectField
                label="어디에 쓸까요?"
                options={[
                  { value: NEW_PROJECT, label: '새 프로젝트 만들기' },
                  ...linkable
                    .filter((p) => !p.has_contract)
                    .map((p) => ({ value: p.id, label: `기존 프로젝트에 연결 · ${p.name} (${p.client.name})` })),
                  ...linkable
                    .filter((p) => p.has_contract)
                    .map((p) => ({ value: p.id, label: `계약서 교체 · ${p.name} (${p.client.name})` })),
                ]}
                value={target ? target.id : NEW_PROJECT}
                onChange={(e) => chooseTarget(e.target.value)}
                hint="계약서 없이 먼저 만든 프로젝트는 연결, 수정 계약서를 받았다면 교체를 고르세요."
              />
            )}
            {replacing && (
              <div className="notice" style={{ margin: '4px 0 16px' }}>
                <p>
                  지금 연결된 계약서가 풀리고 이 계약서로 바뀌어요. 지급 단계도 새로 잡혀요. 예전 계약으로 청구한 인보이스가 있으면(초안·취소 포함) 바꿀 수
                  없어요.
                </p>
              </div>
            )}
            <div className="form-grid">
              <TextField label="프로젝트명" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} fieldClassName="span-2" />
              {linking ? (
                <TextField label="거래처" value={target!.client.name} readOnly disabled />
              ) : (
                <SelectField label="거래처" options={clientOptions} value={clientChoice} onChange={(e) => setClientChoice(e.target.value)} />
              )}
              <SelectField label="직업군" options={JOB_OPTIONS} value={jobType} onChange={(e) => setJobType(e.target.value as JobType)} />
              {!linking && clientChoice === NEW_CLIENT && (
                <TextField
                  label="새 거래처 이름"
                  value={newClientName}
                  onChange={(e) => setNewClientName(e.target.value)}
                  maxLength={100}
                  fieldClassName="span-2"
                  error={!newClientName.trim() ? '거래처 이름을 입력해 주세요.' : undefined}
                />
              )}
              <TextField label="시작일" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
              <TextField
                label="최종 납기"
                type="date"
                value={dueDate}
                min={startDate || undefined}
                onChange={(e) => setDueDate(e.target.value)}
                error={datesOk ? undefined : '시작일보다 빠를 수 없어요.'}
              />
              <AmountField label="계약 금액" value={amount} onChange={setAmount} fieldClassName="span-2" />
            </div>
          </section>

          <section className="card" aria-labelledby="tasks-title">
            <div className="card-head">
              <h2 id="tasks-title" className="card-title">
                작업 초안
              </h2>
              <button type="button" className="link-button" onClick={() => setTasks((ts) => [...ts, { title: '', label: '', due_date: '' }])}>
                + 작업 추가
              </button>
            </div>
            {tasks.length === 0 ? (
              <p className="muted" style={{ margin: 0 }}>
                시작할 작업을 추가하세요. 계약서에서 작업을 추정하는 기능은 AI 분석과 함께 제공돼요. 지금 비워 두고 나중에 칸반에서 추가해도 돼요.
              </p>
            ) : (
              <ul className="edit-rows">
                {tasks.map((t, i) => (
                  <li key={i}>
                    <input className="input" aria-label="작업명" placeholder="작업명" value={t.title} maxLength={200} onChange={(e) => setTask(i, { title: e.target.value })} />
                    <input className="input input-sm" aria-label="분류" placeholder="분류" value={t.label} maxLength={20} onChange={(e) => setTask(i, { label: e.target.value })} />
                    <input className="input input-sm" aria-label="마감일" type="date" value={t.due_date} onChange={(e) => setTask(i, { due_date: e.target.value })} />
                    <button type="button" className="icon-button" aria-label="작업 삭제" onClick={() => setTasks((ts) => ts.filter((_, j) => j !== i))}>
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <aside className="contract-side">
          <section className="card">
            <h2 className="card-title">연결된 계약서</h2>
            <p style={{ margin: '0 0 4px', fontWeight: 600 }}>{draft.contract_title}</p>
            <p className="muted small" style={{ margin: '0 0 12px' }}>
              원본 v{draft.version_no} · 확인 완료
            </p>
            <Link to={`/contracts/${contractId}`} className="link-strong">
              계약서 다시 보기 ↗
            </Link>
          </section>

          <section className="card" aria-labelledby="terms-title">
            <h2 id="terms-title" className="card-title">
              지급 조건
            </h2>
            {draft.payment_terms_text && <p className="muted small">계약서: {draft.payment_terms_text}</p>}
            <ul className="term-rows">
              {terms.map((t, i) => (
                <li key={i}>
                  <div className="term-row-head">
                    <select className="input input-sm" aria-label="지급 단계" value={t.stage} onChange={(e) => setTerm(i, { stage: e.target.value })}>
                      {STAGE_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    <input className="input input-sm" aria-label="단계 이름" value={t.label} maxLength={50} onChange={(e) => setTerm(i, { label: e.target.value })} />
                    {terms.length > 1 && (
                      <button type="button" className="icon-button" aria-label="단계 삭제" onClick={() => setTerms((ts) => ts.filter((_, j) => j !== i))}>
                        ×
                      </button>
                    )}
                  </div>
                  <AmountField label="금액" value={t.amount} onChange={(v) => setTerm(i, { amount: v })} />
                  <TextField
                    label="지급 요건"
                    placeholder="예: 검수 완료 후"
                    value={t.requirement}
                    maxLength={200}
                    onChange={(e) => setTerm(i, { requirement: e.target.value })}
                  />
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="link-button"
              onClick={() => setTerms((ts) => [...ts, { stage: 'other', label: '', amount: '', requirement: '' }])}
            >
              + 단계 추가
            </button>
            <p className={totalMatches ? 'field-hint' : 'field-error'} style={{ margin: '14px 0 8px' }}>
              단계 합계 {formatWon(termsTotal.toString())} / 계약 금액 {formatWon(amount || '0')}
              {!totalMatches && ' — 합계가 같아야 해요'}
            </p>
            <label className="checkbox">
              <input type="checkbox" checked={termsChecked} onChange={(e) => setTermsChecked(e.target.checked)} />
              지급 조건을 확인했습니다
            </label>
          </section>

          <div className="notice">
            <p>지급 단계는 청구의 기준이 돼요. 같은 단계는 두 번 청구할 수 없어요.</p>
          </div>
        </aside>
      </div>
    </form>
  )
}

/** 07 계약 정보로 프로젝트 만들기 (AI 작업 추정 없이 확인값으로 초안을 만든다) */
export function ContractProjectPage() {
  const { contractId = '' } = useParams()
  const [searchParams] = useSearchParams()
  const draft = useProjectDraft(contractId)

  if (draft.isPending) return <Loading />
  if (draft.isError) return <LoadError error={draft.error} onRetry={() => void draft.refetch()} />
  if (draft.data.linked_project_id) {
    return (
      <div className="center-block">
        <p>이 계약서로 만든 프로젝트가 이미 있어요.</p>
        <Link to={`/projects/${draft.data.linked_project_id}`} className="btn btn-primary">
          프로젝트 열기
        </Link>
      </div>
    )
  }
  return (
    <ProjectDraftForm
      contractId={contractId}
      draft={draft.data}
      initialProjectId={searchParams.get('project') ?? recallLinkTarget(contractId) ?? NEW_PROJECT}
    />
  )
}
