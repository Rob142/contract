import { useRef, useState, type FormEvent } from 'react'

import { messageOf } from '../api/messages'
import type { Task } from '../api/projects'
import {
  useAddFeedback,
  useAttachmentActions,
  useAttachments,
  useProjectFeedback,
  useRevisionActions,
  useRevisions,
  useShareLink,
  useShareLinkActions,
  useViewEvents,
  type AttachmentKind,
} from '../api/sharing'
import { formatWon } from '../lib/format'
import { eulReul, withIGa } from '../lib/korean'
import { EmptyState, Loading } from './ui'

const stamp = (iso: string) => {
  const d = new Date(iso)
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
const errorText = (e: unknown) => (e ? messageOf(e) : null)

// ---------------------------------------------------------------- 공유 링크
export function ShareCard({ projectId }: { projectId: string }) {
  const state = useShareLink(projectId)
  const actions = useShareLinkActions(projectId)
  const events = useViewEvents(projectId)
  const [fresh, setFresh] = useState<string | null>(null) // 방금 만든 토큰 (원문은 이때만 볼 수 있다)
  const [copied, setCopied] = useState(false)
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const [confirmRegenerate, setConfirmRegenerate] = useState(false)

  const link = state.data?.link ?? null
  const url = fresh ? `${window.location.origin}/share/${fresh}` : null
  const lastOpen = events.data?.find((e) => e.kind === 'open')

  const copy = async () => {
    if (!url) return
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  const make = (kind: 'create' | 'regenerate') =>
    actions[kind].mutate(undefined, {
      onSuccess: (l) => {
        setFresh(l.token ?? null)
        setCopied(false)
        setConfirmRegenerate(false)
      },
    })

  return (
    <section className="card" aria-labelledby="share-title">
      <div className="card-head">
        <h2 id="share-title" className="card-title">
          클라이언트 공유 링크
        </h2>
        {link && <span className="badge badge-green">공유 중</span>}
      </div>
      {state.isPending ? (
        <Loading />
      ) : !link ? (
        <div className="stack-sm">
          <p className="muted">링크를 받은 클라이언트는 가입 없이 진행 상황·결과물을 보고 피드백과 수정 요청을 남길 수 있어요.</p>
          <div>
            <button type="button" className="btn btn-primary" disabled={actions.create.isPending} onClick={() => make('create')}>
              공유 링크 만들기
            </button>
          </div>
        </div>
      ) : (
        <div className="stack-sm">
          {url ? (
            <div className="inline-add">
              <input className="input" readOnly value={url} aria-label="공유 링크" onFocus={(e) => e.currentTarget.select()} />
              <button type="button" className="btn btn-secondary" onClick={() => void copy()}>
                {copied ? '복사했어요' : '복사'}
              </button>
            </div>
          ) : (
            <p className="muted small">보안을 위해 링크 주소는 만들 때 한 번만 보여 줘요. 잃어버렸다면 다시 발급해 주세요.</p>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={link.allow_feedback}
              onChange={(e) => actions.update.mutate({ allow_feedback: e.target.checked })}
            />
            <span>클라이언트가 피드백·수정 요청을 남길 수 있어요</span>
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={link.show_invoices}
              onChange={(e) => actions.update.mutate({ show_invoices: e.target.checked })}
            />
            <span>발행된 인보이스를 보여 줘요</span>
          </label>
          <p className="muted small">
            {lastOpen ? `마지막으로 연 시각: ${stamp(lastOpen.created_at)}` : '아직 아무도 열어 보지 않았어요.'}
          </p>
          <div className="head-actions">
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={actions.regenerate.isPending}
              onClick={() => (confirmRegenerate ? make('regenerate') : setConfirmRegenerate(true))}
            >
              {confirmRegenerate ? '이미 보낸 링크가 열리지 않아요. 계속할까요?' : '다시 발급 (이전 링크 무효)'}
            </button>
            <button
              type="button"
              className="btn btn-danger-text btn-sm"
              disabled={actions.revoke.isPending}
              onClick={() =>
                confirmRevoke
                  ? actions.revoke.mutate(undefined, { onSuccess: () => { setFresh(null); setConfirmRevoke(false) } })
                  : setConfirmRevoke(true)
              }
            >
              {confirmRevoke ? '정말 공유를 끌까요?' : '공유 끄기'}
            </button>
          </div>
        </div>
      )}
      {errorText(actions.create.error ?? actions.regenerate.error ?? actions.update.error ?? actions.revoke.error) && (
        <p className="field-error" role="alert">
          {errorText(actions.create.error ?? actions.regenerate.error ?? actions.update.error ?? actions.revoke.error)}
        </p>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- 피드백·확인 기록
export function FeedbackCard({ projectId, tasks }: { projectId: string; tasks: Task[] }) {
  const feedback = useProjectFeedback(projectId)
  const events = useViewEvents(projectId)
  const add = useAddFeedback(projectId)
  const [taskId, setTaskId] = useState('')
  const [body, setBody] = useState('')

  const titleOf = (id: string) => tasks.find((t) => t.id === id)?.title ?? '삭제된 단계'
  const acks = (events.data ?? []).filter((e) => e.kind === 'stage_ack')

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const target = taskId || tasks[0]?.id
    if (!target || !body.trim()) return
    add.mutate({ taskId: target, body: body.trim() }, { onSuccess: () => setBody('') })
  }

  return (
    <section className="card" aria-labelledby="feedback-title">
      <div className="card-head">
        <h2 id="feedback-title" className="card-title">
          피드백·확인 기록
        </h2>
        <span className="muted small">수정·삭제할 수 없는 기록이에요</span>
      </div>
      {feedback.isPending ? (
        <Loading />
      ) : (feedback.data ?? []).length === 0 && acks.length === 0 ? (
        <EmptyState title="아직 기록이 없어요." />
      ) : (
        <ul className="row-list">
          {[
            ...(feedback.data ?? []).map((f) => ({ at: f.created_at, key: f.id, node: (
              <>
                <span className={f.author_role === 'client' ? 'badge badge-blue' : 'badge badge-gray'}>
                  {f.author_role === 'client' ? '클라이언트' : '나'}
                </span>{' '}
                <strong>{f.author_name}</strong> · {titleOf(f.task_id)}
                <p>{f.body}</p>
              </>
            ) })),
            ...acks.map((a) => ({ at: a.created_at, key: a.id, node: (
              <span className="muted">
                ✓ {withIGa(a.viewer_name ?? '클라이언트')} {a.task_id ? `‘${titleOf(a.task_id)}’${eulReul(titleOf(a.task_id))}` : '단계를'} 확인했어요
              </span>
            ) })),
          ]
            .sort((a, b) => b.at.localeCompare(a.at))
            .map((row) => (
              <li key={row.key}>
                <span className="muted small">{stamp(row.at)}</span>
                <div>{row.node}</div>
              </li>
            ))}
        </ul>
      )}
      {tasks.length > 0 && (
        <form className="inline-add" onSubmit={submit}>
          <select className="input" value={taskId || tasks[0]?.id} onChange={(e) => setTaskId(e.target.value)} aria-label="단계">
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
          <input className="input" value={body} onChange={(e) => setBody(e.target.value)} maxLength={2000} placeholder="답변·메모 남기기" aria-label="답변" />
          <button type="submit" className="btn btn-secondary" disabled={add.isPending || !body.trim()}>
            남기기
          </button>
        </form>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- 수정 요청 카운터
export function RevisionCard({ projectId, included }: { projectId: string; included: number | null }) {
  const state = useRevisions(projectId)
  const actions = useRevisionActions(projectId)
  const [excluding, setExcluding] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [quoting, setQuoting] = useState<string | null>(null)
  const [quote, setQuote] = useState({ title: '추가 수정', amount: '' })

  if (state.isPending) return <Loading />
  if (state.isError) return null
  const { counter, requests, quotes } = state.data

  return (
    <section className="card" aria-labelledby="revision-title">
      <div className="card-head">
        <h2 id="revision-title" className="card-title">
          수정 요청 카운터
        </h2>
        <span className={counter.remaining === 0 ? 'badge badge-red' : 'badge badge-gray'}>
          {included === null ? `${counter.used}회 요청 · 포함 횟수 미설정` : `${counter.used} / ${included}회`}
        </span>
      </div>
      {requests.length === 0 ? (
        <EmptyState title="수정 요청이 아직 없어요." />
      ) : (
        <ul className="row-list">
          {requests.map((r) => (
            <li key={r.id}>
              <div>
                <strong>{r.seq}회차</strong> · {r.requester_name} <span className="muted small">{stamp(r.created_at)}</span>{' '}
                {r.over_limit && <span className="badge badge-red">포함 횟수 초과</span>}{' '}
                {r.excluded_at && <span className="badge badge-gray">카운트 제외 · {r.excluded_reason}</span>}
                <p>{r.body}</p>
                {!r.excluded_at &&
                  (excluding === r.id ? (
                    <form
                      className="inline-add"
                      onSubmit={(e) => {
                        e.preventDefault()
                        actions.exclude.mutate({ id: r.id, reason: reason.trim() }, { onSuccess: () => { setExcluding(null); setReason('') } })
                      }}
                    >
                      <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="제외 사유" maxLength={200} aria-label="제외 사유" autoFocus />
                      <button type="submit" className="btn btn-secondary btn-sm" disabled={!reason.trim()}>
                        제외
                      </button>
                    </form>
                  ) : (
                    <button type="button" className="link-button" onClick={() => setExcluding(r.id)}>
                      카운트에서 제외
                    </button>
                  ))}{' '}
                {r.over_limit && (
                  quoting === r.id ? (
                    <form
                      className="inline-add"
                      onSubmit={(e) => {
                        e.preventDefault()
                        actions.quote.mutate(
                          { title: quote.title.trim(), amount: quote.amount, revision_request_id: r.id },
                          { onSuccess: () => setQuoting(null) },
                        )
                      }}
                    >
                      <input className="input" value={quote.title} onChange={(e) => setQuote({ ...quote, title: e.target.value })} aria-label="견적 제목" />
                      <input className="input" inputMode="numeric" value={quote.amount} onChange={(e) => setQuote({ ...quote, amount: e.target.value.replace(/\D/g, '') })} placeholder="금액(원)" aria-label="견적 금액" />
                      <button type="submit" className="btn btn-primary btn-sm" disabled={!quote.amount || !quote.title.trim()}>
                        견적 저장
                      </button>
                    </form>
                  ) : (
                    <button type="button" className="link-button" onClick={() => setQuoting(r.id)}>
                      추가 견적 작성
                    </button>
                  )
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {quotes.length > 0 && (
        <>
          <h3 className="list-subhead">추가 견적</h3>
          <ul className="row-list">
            {quotes.map((q) => (
              <li key={q.id}>
                <strong>{q.title}</strong> · {formatWon(q.amount)}
              </li>
            ))}
          </ul>
        </>
      )}
      {errorText(actions.exclude.error ?? actions.quote.error) && (
        <p className="field-error" role="alert">
          {errorText(actions.exclude.error ?? actions.quote.error)}
        </p>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- 첨부 (결과물·증빙)
const KIND_LABEL: Record<AttachmentKind, string> = { deliverable: '결과물', evidence: '증빙', other: '기타' }
const DOC_TYPES = [
  ['tax_invoice', '세금계산서'],
  ['cash_receipt', '현금영수증'],
  ['receipt', '영수증'],
  ['contract_copy', '계약서 사본'],
  ['other', '기타'],
] as const

export function AttachmentsCard({ projectId, tasks }: { projectId: string; tasks: Task[] }) {
  const list = useAttachments(projectId)
  const actions = useAttachmentActions(projectId)
  const fileRef = useRef<HTMLInputElement>(null)
  const [kind, setKind] = useState<AttachmentKind>('deliverable')
  const [taskId, setTaskId] = useState('')
  const [docType, setDocType] = useState('')
  const [issuedOn, setIssuedOn] = useState('')
  const [amount, setAmount] = useState('')
  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const [linkError, setLinkError] = useState<string | null>(null)
  const error = linkError ?? errorText(actions.addFile.error ?? actions.addLink.error ?? actions.remove.error)
  // 올린 뒤에는 단계·증빙 정보를 비운다. 다음 자료에 이전 단계가 따라붙지 않게 한다 (종류는 유지)
  const resetForm = () => {
    setTitle('')
    setUrl('')
    setTaskId('')
    setDocType('')
    setIssuedOn('')
    setAmount('')
    setLinkError(null)
  }

  // 새 시도를 시작하면 이전 시도의 오류 문구를 지운다
  const clearErrors = () => {
    setLinkError(null)
    actions.addFile.reset()
    actions.addLink.reset()
    actions.remove.reset()
  }

  const onFile = () => {
    const file = fileRef.current?.files?.[0]
    if (!file) return
    clearErrors()
    const form = new FormData()
    form.append('file', file)
    form.append('kind', kind)
    if (title.trim()) form.append('title', title.trim())
    if (taskId) form.append('task_id', taskId)
    if (kind === 'evidence') {
      if (docType) form.append('doc_type', docType)
      if (issuedOn) form.append('issued_on', issuedOn)
      if (amount) form.append('amount', amount)
    }
    actions.addFile.mutate(form, {
      onSuccess: resetForm,
      onSettled: () => {
        if (fileRef.current) fileRef.current.value = '' // 같은 파일을 다시 고를 수 있게
      },
    })
  }
  const onLink = (e: FormEvent) => {
    e.preventDefault()
    clearErrors()
    if (!/^https?:\/\//i.test(url.trim())) {
      setLinkError('http:// 또는 https://로 시작하는 주소를 넣어 주세요.')
      return
    }
    actions.addLink.mutate(
      { title: title.trim() || url.trim(), url: url.trim(), kind, task_id: taskId || null },
      { onSuccess: resetForm },
    )
  }

  return (
    <section className="card" aria-labelledby="attach-title">
      <div className="card-head">
        <h2 id="attach-title" className="card-title">
          결과물·증빙
        </h2>
      </div>
      {list.isPending ? (
        <Loading />
      ) : (list.data ?? []).length === 0 ? (
        <EmptyState title="올린 자료가 없어요." />
      ) : (
        <ul className="row-list">
          {(list.data ?? []).map((a) => (
            <li key={a.id}>
              <span className={a.kind === 'deliverable' ? 'badge badge-blue' : 'badge badge-gray'}>{KIND_LABEL[a.kind]}</span>{' '}
              {a.url ? (
                <a href={a.url} target="_blank" rel="noopener noreferrer">
                  {a.title}
                </a>
              ) : (
                <a href={`/api/v1/attachments/${a.id}/file?download=true`}>{a.title}</a>
              )}
              {a.task_id && <span className="muted small"> · {tasks.find((t) => t.id === a.task_id)?.title}</span>}
              {a.amount && <span className="muted small"> · {formatWon(a.amount)}</span>}{' '}
              {confirmDelete === a.id ? (
                <>
                  <button
                    type="button"
                    className="link-button"
                    disabled={actions.remove.isPending}
                    onClick={() => {
                      clearErrors()
                      actions.remove.mutate(a.id, { onSettled: () => setConfirmDelete(null) })
                    }}
                  >
                    정말 삭제
                  </button>{' '}
                  <button type="button" className="link-button" onClick={() => setConfirmDelete(null)}>
                    취소
                  </button>
                </>
              ) : (
                <button type="button" className="link-button" onClick={() => setConfirmDelete(a.id)}>
                  삭제
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <form className="stack-sm" onSubmit={onLink}>
        <div className="inline-add">
          <select className="input" value={kind} onChange={(e) => setKind(e.target.value as AttachmentKind)} aria-label="종류">
            <option value="deliverable">결과물</option>
            <option value="evidence">증빙</option>
            <option value="other">기타</option>
          </select>
          <select className="input" value={taskId} onChange={(e) => setTaskId(e.target.value)} aria-label="단계">
            <option value="">단계 선택 안 함</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
          <input className="input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="제목" maxLength={200} aria-label="제목" />
        </div>
        {kind === 'evidence' && (
          <div className="inline-add">
            <select className="input" value={docType} onChange={(e) => setDocType(e.target.value)} aria-label="증빙 종류">
              <option value="">증빙 종류</option>
              {DOC_TYPES.map(([v, l]) => (
                <option key={v} value={v}>
                  {l}
                </option>
              ))}
            </select>
            <input className="input" type="date" value={issuedOn} onChange={(e) => setIssuedOn(e.target.value)} aria-label="발행일" />
            <input className="input" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ''))} placeholder="금액(원)" aria-label="금액" />
          </div>
        )}
        <div className="inline-add">
          <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https:// 링크 붙여넣기" aria-label="링크" />
          <button type="submit" className="btn btn-secondary" disabled={!url.trim() || actions.addLink.isPending}>
            링크 추가
          </button>
          <input ref={fileRef} type="file" className="visually-hidden" id="attach-file" onChange={onFile} />
          <label htmlFor="attach-file" className="btn btn-secondary" aria-disabled={actions.addFile.isPending}>
            {actions.addFile.isPending ? '올리는 중…' : '파일 올리기'}
          </label>
        </div>
        <p className="muted small">결과물로 올린 자료만 클라이언트 공유 페이지에 보여요. 증빙·기타는 나만 볼 수 있어요.</p>
      </form>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
