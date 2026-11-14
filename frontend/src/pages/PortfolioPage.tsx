import { useState } from 'react'
import { Link } from 'react-router'

import { ApiError } from '../api/client'
import { useProjects } from '../api/projects'
import {
  usePortfolio,
  usePortfolioActions,
  usePortfolioDraft,
  type Portfolio,
  type PortfolioDraft,
} from '../api/sharing'
import { Dialog } from '../components/Dialog'
import { EmptyState, LoadError, Loading } from '../components/ui'
import { JOB_TYPE_LABELS, formatFullDate } from '../lib/format'

const VISIBILITY = { private: '비공개', link: '링크 공유', public: '전체 공개' } as const
const STATUS = { draft: '초안', ready: '공개 준비됨', archived: '보관' } as const
const errorText = (e: unknown) => (e instanceof ApiError ? e.message : e ? '요청에 실패했어요.' : null)

/** 초안을 고쳐 카드로 확정한다 */
function DraftDialog({ draft, onClose }: { draft: PortfolioDraft; onClose: () => void }) {
  const actions = usePortfolioActions()
  const [title, setTitle] = useState(draft.title)
  const [description, setDescription] = useState(draft.description ?? '')
  const [assets, setAssets] = useState(() => new Set(draft.assets.map((a) => a.attachment_id)))
  const [quotes, setQuotes] = useState(() => new Set<string>())
  const toggle = (set: Set<string>, id: string, apply: (s: Set<string>) => void) => {
    const next = new Set(set)
    if (!next.delete(id)) next.add(id)
    apply(next)
  }

  const save = () =>
    actions.create.mutate(
      {
        project_id: draft.project_id,
        title: title.trim(),
        description: description.trim() || null,
        period_start: draft.period_start,
        period_end: draft.period_end,
        asset_ids: [...assets],
        quotes: draft.quote_candidates
          .filter((q) => quotes.has(q.feedback_id))
          .map((q) => ({ feedback_id: q.feedback_id, quote: q.quote, anonymize: true })),
      },
      { onSuccess: onClose },
    )

  return (
    <Dialog
      open
      onClose={onClose}
      title="포트폴리오 카드 초안"
      footer={
        <>
          <span className="spacer" />
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            취소
          </button>
          <button type="button" className="btn btn-primary" disabled={!title.trim() || actions.create.isPending} onClick={save}>
            초안 저장
          </button>
        </>
      }
    >
      <div className="stack-sm">
        {!draft.project_completed && <div className="notice">아직 완료하지 않은 프로젝트예요. 초안은 만들 수 있어요.</div>}
        <label className="field">
          <span className="field-label">제목</span>
          <input className="input" value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">설명</span>
          <textarea className="input" rows={3} value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <p className="muted small">
          {JOB_TYPE_LABELS[draft.job_type]} · {draft.period_start ? formatFullDate(draft.period_start) : '시작일 미정'} ~{' '}
          {draft.period_end ? formatFullDate(draft.period_end) : '종료일 미정'}
        </p>
        <fieldset className="stack-sm">
          <legend className="field-label">넣을 결과물</legend>
          {draft.assets.length === 0 && <p className="muted small">프로젝트에 올린 결과물이 없어요.</p>}
          {draft.assets.map((a) => (
            <label key={a.attachment_id} className="checkbox">
              <input type="checkbox" checked={assets.has(a.attachment_id)} onChange={() => toggle(assets, a.attachment_id, setAssets)} />
              <span>{a.title}</span>
            </label>
          ))}
        </fieldset>
        <fieldset className="stack-sm">
          <legend className="field-label">넣을 클라이언트 피드백 (공개 전에 동의 확인이 필요해요)</legend>
          {draft.quote_candidates.length === 0 && <p className="muted small">받은 피드백이 없어요.</p>}
          {draft.quote_candidates.map((q) => (
            <label key={q.feedback_id} className="checkbox">
              <input type="checkbox" checked={quotes.has(q.feedback_id)} onChange={() => toggle(quotes, q.feedback_id, setQuotes)} />
              <span>&ldquo;{q.quote}&rdquo;</span>
            </label>
          ))}
        </fieldset>
        {actions.create.isError && (
          <p className="field-error" role="alert">
            {errorText(actions.create.error)}
          </p>
        )}
      </div>
    </Dialog>
  )
}

function CardEditor({ item, onClose }: { item: Portfolio; onClose: () => void }) {
  const actions = usePortfolioActions()
  const [title, setTitle] = useState(item.title)
  const [description, setDescription] = useState(item.description ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const patch = (body: Parameters<typeof actions.update.mutate>[0]['body']) =>
    actions.update.mutate({ id: item.id, body: { ...body, version: item.version } })
  const shareUrl = item.share_slug ? `${window.location.origin}/p/${item.share_slug}` : null

  return (
    <Dialog
      open
      onClose={onClose}
      title="포트폴리오 카드"
      footer={
        <>
          <button
            type="button"
            className="btn btn-danger-text"
            onClick={() => (confirmDelete ? actions.remove.mutate(item.id, { onSuccess: onClose }) : setConfirmDelete(true))}
          >
            {confirmDelete ? '정말 삭제할까요?' : '카드 삭제'}
          </button>
          <span className="spacer" />
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            닫기
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!title.trim() || actions.update.isPending}
            onClick={() => patch({ title: title.trim(), description: description.trim() || null })}
          >
            제목·설명 저장
          </button>
        </>
      }
    >
      <div className="stack-sm">
        <label className="field">
          <span className="field-label">제목</span>
          <input className="input" value={title} maxLength={100} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="field">
          <span className="field-label">설명</span>
          <textarea className="input" rows={3} value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} />
        </label>

        <h3 className="list-subhead">공개 설정</h3>
        <label className="checkbox">
          <input type="checkbox" checked={item.status === 'ready'} onChange={(e) => patch({ status: e.target.checked ? 'ready' : 'draft' })} />
          <span>공개할 준비가 됐어요 (체크해야 공개할 수 있어요)</span>
        </label>
        <label className="field">
          <span className="field-label">공개 범위</span>
          <select
            className="input"
            value={item.visibility}
            disabled={item.status !== 'ready'}
            onChange={(e) => patch({ visibility: e.target.value as Portfolio['visibility'] })}
          >
            {Object.entries(VISIBILITY).map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </select>
        </label>
        {shareUrl && item.visibility !== 'private' && (
          <input className="input" readOnly value={shareUrl} aria-label="공개 주소" onFocus={(e) => e.currentTarget.select()} />
        )}
        <label className="checkbox">
          <input type="checkbox" checked={item.show_client_name} onChange={(e) => patch({ show_client_name: e.target.checked })} />
          <span>클라이언트명 보여 주기 ({item.client_name}) — 클라이언트 동의를 받은 경우에만 켜 주세요</span>
        </label>
        {item.quotes.length > 0 && (
          <label className="checkbox">
            <input type="checkbox" checked={item.feedback_consent_at !== null} onChange={(e) => patch({ feedback_consent: e.target.checked })} />
            <span>피드백 {item.quotes.length}건을 공개해도 된다고 클라이언트에게 동의받았어요 (이름은 익명으로 표시돼요)</span>
          </label>
        )}
        <p className="muted small">금액과 계약 조건은 공개 페이지에 나오지 않아요.</p>
        {(actions.update.isError || actions.remove.isError) && (
          <p className="field-error" role="alert">
            {errorText(actions.update.error ?? actions.remove.error)}
          </p>
        )}
      </div>
    </Dialog>
  )
}

export function PortfolioPage() {
  const portfolio = usePortfolio()
  const projects = useProjects('all')
  const makeDraft = usePortfolioDraft()
  const [draft, setDraft] = useState<PortfolioDraft | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [pick, setPick] = useState('')

  const used = new Set((portfolio.data?.items ?? []).map((i) => i.project_id))
  const candidates = (projects.data?.items ?? []).filter((p) => !used.has(p.id))
  const editingItem = portfolio.data?.items.find((i) => i.id === editing)

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">나의 워크스페이스</p>
          <h1 className="page-title">포트폴리오</h1>
          <p className="page-desc">완료한 프로젝트의 결과물·기간·직군·피드백으로 카드 초안을 만들어요.</p>
        </div>
        <div className="head-actions">
          <select className="input" value={pick} onChange={(e) => setPick(e.target.value)} aria-label="카드로 만들 프로젝트">
            <option value="">프로젝트 선택</option>
            {candidates.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
                {p.status === 'completed' ? ' (완료)' : ''}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn btn-primary"
            disabled={!pick || makeDraft.isPending}
            onClick={() => makeDraft.mutate(pick, { onSuccess: setDraft })}
          >
            카드 초안 만들기
          </button>
        </div>
      </div>

      {portfolio.isPending ? (
        <Loading />
      ) : portfolio.isError ? (
        <LoadError error={portfolio.error} onRetry={() => void portfolio.refetch()} />
      ) : portfolio.data.items.length === 0 ? (
        <EmptyState title="아직 포트폴리오 카드가 없어요.">
          위에서 프로젝트를 고르면 결과물과 피드백으로 초안을 만들어 줘요. <Link to="/projects">프로젝트 보기</Link>
        </EmptyState>
      ) : (
        <div className="project-grid">
          {portfolio.data.items.map((i) => (
            <button key={i.id} type="button" className="card project-card" onClick={() => setEditing(i.id)}>
              <div className="project-card-top">
                <span className="badge badge-gray">{JOB_TYPE_LABELS[i.job_type]}</span>
                <span className={i.visibility === 'private' ? 'badge badge-gray' : 'badge badge-green'}>{VISIBILITY[i.visibility]}</span>
              </div>
              <h2 className="project-card-title">{i.title}</h2>
              <p className="muted small">
                {STATUS[i.status]} · 결과물 {i.assets.length}개 · 피드백 {i.quotes.length}건
              </p>
            </button>
          ))}
        </div>
      )}
      {makeDraft.isError && (
        <p className="field-error" role="alert">
          {errorText(makeDraft.error)}
        </p>
      )}
      {draft && <DraftDialog draft={draft} onClose={() => setDraft(null)} />}
      {editingItem && <CardEditor key={editingItem.id + editingItem.version} item={editingItem} onClose={() => setEditing(null)} />}
    </>
  )
}
