import { useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import { ApiError } from '../api/client'
import { usePublicActions, usePublicProject, type PublicTask } from '../api/sharing'
import { Loading, ProgressBar } from '../components/ui'
import { useNoIndex } from '../lib/useNoIndex'
import { formatFullDate, formatWon } from '../lib/format'

const NAME_KEY = 'fh-client-name'
const loadName = () => {
  try {
    return localStorage.getItem(NAME_KEY) ?? ''
  } catch {
    return ''
  }
}
const saveName = (name: string) => {
  try {
    localStorage.setItem(NAME_KEY, name)
  } catch {
    /* 저장하지 못해도 동작에는 문제가 없다 */
  }
}
const STATUS: Record<PublicTask['status'], { label: string; className: string }> = {
  todo: { label: '예정', className: 'badge badge-gray' },
  doing: { label: '진행 중', className: 'badge badge-blue' },
  done: { label: '완료', className: 'badge badge-green' },
}
const stamp = (iso: string) => {
  const d = new Date(iso)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function TaskBlock({
  task,
  token,
  name,
  canFeedback,
}: {
  task: PublicTask
  token: string
  name: string
  canFeedback: boolean
}) {
  const actions = usePublicActions(token)
  const [text, setText] = useState('')
  const status = STATUS[task.status]

  const send = (e: FormEvent) => {
    e.preventDefault()
    if (!text.trim()) return
    saveName(name.trim())
    actions.feedback.mutate({ taskId: task.id, body: text.trim(), name: name.trim() }, { onSuccess: () => setText('') })
  }

  return (
    <li className="card">
      <div className="card-head">
        <h3 className="card-title">{task.title}</h3>
        <span className={status.className}>{status.label}</span>
      </div>
      {task.completed_at && <p className="muted small">{stamp(task.completed_at)} 완료</p>}
      {task.deliverables.length > 0 && (
        <ul className="row-list">
          {task.deliverables.map((d) => (
            <li key={d.id}>
              {d.url ? (
                <a href={d.url} target="_blank" rel="noopener noreferrer">
                  {d.title}
                </a>
              ) : (
                <a href={`/api/v1/public/p/${token}/attachments/${d.id}/file`}>{d.title}</a>
              )}
            </li>
          ))}
        </ul>
      )}
      {task.feedback.length > 0 && (
        <ul className="row-list">
          {task.feedback.map((f) => (
            <li key={f.id}>
              <span className="muted small">
                {stamp(f.created_at)} · {f.author_role === 'client' ? f.author_name : `${f.author_name} (작업자)`}
              </span>
              <p>{f.body}</p>
            </li>
          ))}
        </ul>
      )}
      <div className="head-actions">
        {task.acknowledged_at ? (
          <span className="muted small">✓ {stamp(task.acknowledged_at)}에 확인했어요</span>
        ) : task.status !== 'todo' ? (
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            disabled={actions.ack.isPending}
            onClick={() => {
              saveName(name.trim())
              actions.ack.mutate({ taskId: task.id, viewer: name.trim() })
            }}
          >
            확인했어요
          </button>
        ) : null}
        {!task.acknowledged_at && task.status !== 'todo' && (
          <span className="muted small">단계 내용을 봤다는 표시로 기록돼요. 승인이나 동의를 뜻하지는 않아요.</span>
        )}
      </div>
      {canFeedback && (
        <form className="inline-add" onSubmit={send}>
          <input
            className="input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={2000}
            placeholder="이 단계에 대한 의견을 남겨 주세요"
            aria-label={`${task.title} 피드백`}
          />
          <button type="submit" className="btn btn-secondary" disabled={actions.feedback.isPending || !text.trim()}>
            남기기
          </button>
        </form>
      )}
      {(actions.ack.isError || actions.feedback.isError) && (
        <p className="field-error" role="alert">
          잠시 후 다시 시도해 주세요.
        </p>
      )}
    </li>
  )
}

/** 가입 없이 열리는 클라이언트용 진행 현황 페이지 (/share/:token) */
export function ClientSharePage() {
  const { token = '' } = useParams()
  useNoIndex()
  const project = usePublicProject(token)
  const actions = usePublicActions(token)
  const [name, setName] = useState(loadName)
  const [text, setText] = useState('')
  const [overOk, setOverOk] = useState(false)
  const [sent, setSent] = useState(false)

  if (project.isPending) return <Loading />
  if (project.isError) {
    const gone = project.error instanceof ApiError && project.error.status === 404
    return (
      <main className="app-main client-page">
        <div className="card">
          <h1 className="page-title">{gone ? '열 수 없는 링크예요' : '불러오지 못했어요'}</h1>
          <p className="muted">
            {gone
              ? '링크가 만료됐거나 공유가 중단됐어요. 작업자에게 새 링크를 요청해 주세요.'
              : '잠시 후 다시 시도해 주세요.'}
          </p>
        </div>
      </main>
    )
  }

  const p = project.data
  const isOver = p.revision.remaining === 0
  const sendRevision = (e: FormEvent) => {
    e.preventDefault()
    if (!text.trim() || (isOver && !overOk)) return
    saveName(name.trim())
    actions.revision.mutate(
      { body: text.trim(), name: name.trim() },
      {
        onSuccess: () => {
          setText('')
          setOverOk(false)
          setSent(true)
        },
      },
    )
  }

  return (
    <main className="app-main client-page">
      <div className="page-head">
        <div>
          <p className="page-eyebrow">{p.freelancer_name}님의 작업 진행 현황</p>
          <h1 className="page-title">{p.name}</h1>
        </div>
      </div>

      <section className="card stack-sm" aria-label="진행도">
        <ProgressBar value={p.progress_pct} label="전체 진행도" />
        <div className="summary-bar">
          <span>
            <span className="muted">계약 금액</span> <strong>{formatWon(p.contract.contract_amount)}</strong>
          </span>
          <span>
            <span className="muted">기간</span>{' '}
            <strong>
              {p.contract.start_date ? formatFullDate(p.contract.start_date) : '미정'} —{' '}
              {p.contract.due_date ? formatFullDate(p.contract.due_date) : '미정'}
            </strong>
          </span>
          {p.contract.included_revisions !== null && (
            <span>
              <span className="muted">포함 수정</span> <strong>{p.contract.included_revisions}회</strong>
            </span>
          )}
        </div>
      </section>

      <section className="card stack-sm" aria-label="이름">
        <label className="field-label" htmlFor="client-name">
          남기는 분 이름 (선택)
        </label>
        <input
          id="client-name"
          className="input"
          value={name}
          maxLength={50}
          onChange={(e) => setName(e.target.value)}
          placeholder="예: 박OO 대리"
        />
        <p className="muted small">확인 시각과 의견은 기록으로 남아요. 이름을 적어 두면 누가 남겼는지 구분돼요.</p>
      </section>

      <ul className="stack" style={{ listStyle: 'none', padding: 0 }}>
        {p.tasks.map((t) => (
          <TaskBlock key={t.id} task={t} token={token} name={name} canFeedback={p.allow_feedback} />
        ))}
      </ul>

      {p.allow_feedback && (
        <section className="card stack-sm" aria-labelledby="rev-title">
          <div className="card-head">
            <h2 id="rev-title" className="card-title">
              수정 요청
            </h2>
            <span className={p.revision.remaining === 0 ? 'badge badge-red' : 'badge badge-gray'}>
              {p.revision.included === null
                ? `${p.revision.used}회 요청`
                : `남은 횟수 ${p.revision.remaining} / ${p.revision.included}`}
            </span>
          </div>
          {p.revision.remaining === 0 && (
            <div className="notice">포함된 수정 횟수를 모두 사용했어요. 추가 수정은 별도 비용이 들 수 있어요. 요청은 기록되고, 작업자가 견적을 안내해 드려요.</div>
          )}
          <form className="stack-sm" onSubmit={sendRevision}>
            <textarea
              className="input"
              rows={3}
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                setSent(false)
              }}
              maxLength={2000}
              placeholder="수정해 주실 내용을 적어 주세요. 어느 단계의 어떤 부분인지 함께 적어 주시면 좋아요."
              aria-label="수정 요청 내용"
            />
            {isOver && (
              <label className="confirm-over">
                <input type="checkbox" checked={overOk} onChange={(e) => setOverOk(e.target.checked)} />
                <span>포함된 횟수를 넘는 수정이라 추가 비용이 들 수 있다는 점을 확인했어요.</span>
              </label>
            )}
            <div>
              <button
                type="submit"
                className="btn btn-primary"
                disabled={actions.revision.isPending || !text.trim() || (isOver && !overOk)}
              >
                {isOver ? '추가 수정 요청 보내기' : '수정 요청 보내기'}
              </button>
            </div>
            {sent && (
              <p className="muted small" role="status">
                요청이 접수됐어요. 작업자가 확인하면 이 페이지에 답변이 남아요.
              </p>
            )}
          </form>
          {p.revision_requests.length > 0 && (
            <ul className="row-list">
              {p.revision_requests.map((r) => (
                <li key={r.id}>
                  <strong>{r.seq}회차</strong> <span className="muted small">{stamp(r.created_at)}</span>
                  {r.excluded_at ? (
                    <span className="badge badge-gray">횟수 제외</span>
                  ) : (
                    r.over_limit && <span className="badge badge-red">포함 횟수 초과</span>
                  )}
                  <p>{r.body}</p>
                </li>
              ))}
            </ul>
          )}
          {actions.revision.isError && (
            <p className="field-error" role="alert">
              요청을 보내지 못했어요. 잠시 후 다시 시도해 주세요.
            </p>
          )}
        </section>
      )}

      {p.invoices && p.invoices.length > 0 && (
        <section className="card" aria-labelledby="inv-title">
          <h2 id="inv-title" className="card-title">
            인보이스
          </h2>
          <ul className="row-list">
            {p.invoices.map((i) => (
              <li key={i.invoice_no}>
                <strong>{i.invoice_no}</strong> · {formatWon(i.total)}
                {i.due_date && i.status !== 'paid' && (
                  <span className="muted small"> · 입금 예정 {formatFullDate(i.due_date)}</span>
                )}{' '}
                <span className={i.status === 'paid' ? 'badge badge-green' : 'badge badge-amber'}>
                  {i.status === 'paid' ? '입금 완료' : '입금 대기'}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  )
}
