import { useState } from 'react'
import { Link, useParams } from 'react-router'

import { useAnalysis, useRevisionPrompt, type AnalysisResult } from '../api/analysis'
import { useContract } from '../api/contracts'
import { messageOf } from '../api/messages'
import { EmptyState, FilterTabs, LoadError, Loading } from '../components/ui'
import { formatFullDate, JOB_TYPE_SHORT, localDateOf } from '../lib/format'

type Filter = 'all' | 'caution' | 'needs_check' | 'confirmed'

const STATUS_BADGE: Record<AnalysisResult['status'], { label: string; className: string }> = {
  not_found: { label: '미발견', className: 'badge badge-amber' },
  unclear: { label: '불명확', className: 'badge badge-amber' },
  found: { label: '발견', className: 'badge badge-green' },
}

/** 중요도 높은 미해결 항목은 "꼭 협의"로 따로 보인다 (UX 문서 3장 C) */
const isMustTalk = (r: AnalysisResult) => r.review_level !== 'confirmed' && r.importance === 'high'

const IMPORTANCE_ORDER: Record<AnalysisResult['importance'], number> = { high: 0, medium: 1, low: 2 }

function ResultCard({
  result,
  contractId,
  selected,
  onToggle,
}: {
  result: AnalysisResult
  contractId: string
  selected: boolean
  onToggle: () => void
}) {
  const badge = STATUS_BADGE[result.status]
  const canPrompt = result.review_level !== 'confirmed'
  return (
    <article className={`card result-card level-${result.review_level}`}>
      <div className="card-head">
        <h3 className="result-title">{result.title}</h3>
        {isMustTalk(result) && <span className="badge badge-red">꼭 협의</span>}
        <span className={badge.className}>{badge.label}</span>
      </div>
      {result.explanation && <p className="result-text">{result.explanation}</p>}

      {result.status === 'not_found' ? (
        <blockquote className="evidence">
          <span>검토 범위: 계약서 전체</span>
          <span className="muted small">미발견은 제공된 문서에서 확인하지 못했다는 뜻이에요.</span>
        </blockquote>
      ) : (
        result.evidence.map((ev) => (
          <blockquote key={ev.block_key} className={ev.valid ? 'evidence' : 'evidence is-invalid'}>
            <span>“{ev.quote}”</span>
            <span className="muted small">
              원문 {ev.page_no}쪽
              {ev.valid ? (
                <>
                  {' '}
                  <Link to={`/contracts/${contractId}?page=${ev.page_no}&block=${ev.block_key}`} className="link-strong">
                    원문 보기 ↗
                  </Link>
                </>
              ) : (
                ' · 원문에서 이 문장을 찾지 못했어요. 직접 확인해 주세요.'
              )}
            </span>
          </blockquote>
        ))
      )}

      {result.validation_status === 'failed' && result.evidence.length === 0 && result.status !== 'not_found' && (
        <p className="field-error small">분석 결과의 근거가 확인되지 않아 확정하지 않았어요. 원문을 직접 확인해 주세요.</p>
      )}
      {result.user_action && <p className="muted">{result.user_action}</p>}
      {result.suggestion && result.review_level !== 'confirmed' && <p className="muted small">수정 방향: {result.suggestion}</p>}

      <div className="result-foot">
        <span className="muted small">
          {result.rule_title} 규칙 {result.rule_id}
        </span>
        {canPrompt && (
          <label className="checkbox include-check">
            <input type="checkbox" checked={selected} onChange={onToggle} />
            수정 프롬프트에 포함
          </label>
        )}
      </div>
    </article>
  )
}

/** 06 계약서 분석 결과 */
export function AnalysisPage() {
  const { contractId = '' } = useParams()
  const contract = useContract(contractId)
  const view = useAnalysis(contractId)
  const prompt = useRevisionPrompt(contractId)
  const [filter, setFilter] = useState<Filter>('all')
  const [selected, setSelected] = useState<Set<string> | null>(null)
  const [copied, setCopied] = useState(false)

  if (view.isPending || contract.isPending) return <Loading />
  if (view.isError) return <LoadError error={view.error} onRetry={() => void view.refetch()} />
  if (contract.isError) return <LoadError error={contract.error} onRetry={() => void contract.refetch()} />

  const analysis = view.data.analysis
  if (!analysis) {
    return (
      <div className="card">
        <EmptyState title="아직 분석 결과가 없어요.">
          <Link to={`/contracts/${contractId}`} className="btn btn-secondary">
            계약서에서 분석 시작하기
          </Link>
        </EmptyState>
      </div>
    )
  }

  // 처음에는 주의·확인 필요 항목을 모두 골라 둔다
  const defaultSelected = new Set(analysis.results.filter((r) => r.review_level !== 'confirmed').map((r) => r.id))
  const picked = selected ?? defaultSelected
  const toggle = (id: string) => {
    const next = new Set(picked)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
    prompt.reset()
    setCopied(false)
  }

  const c = contract.data
  const counts = analysis.counts
  // 중요도 높은 항목을 먼저 보여준다 (같은 중요도면 기존 순서 유지)
  const sorted = [...analysis.results].sort((a, b) => {
    const aMust = isMustTalk(a)
    const bMust = isMustTalk(b)
    if (aMust !== bMust) return aMust ? -1 : 1
    return (IMPORTANCE_ORDER[a.importance] ?? 1) - (IMPORTANCE_ORDER[b.importance] ?? 1)
  })
  const items = sorted.filter((r) => filter === 'all' || r.review_level === filter)
  const mustTalk = analysis.results.filter(isMustTalk).length
  const needsCheck = counts.caution + counts.needs_check - mustTalk

  const copy = async () => {
    if (!prompt.data) return
    try {
      await navigator.clipboard.writeText(prompt.data.prompt)
      setCopied(true)
    } catch {
      // http(LAN) 접속처럼 클립보드를 쓸 수 없는 환경: 텍스트를 선택해 직접 복사
      const area = document.getElementById('revision-prompt') as HTMLTextAreaElement | null
      area?.select()
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">
            <Link to={`/contracts/${contractId}`}>계약서</Link> / 분석 결과
          </p>
          <h1 className="page-title">계약서 분석 결과</h1>
          <p className="page-desc">
            {c.title} · {JOB_TYPE_SHORT[analysis.job_type]} 규칙 적용 · {analysis.llm_mode === 'local' ? '로컬 LLM' : '상용 API'} ·{' '}
            {analysis.model_id} · 원본 v{c.version_no}
            {analysis.analyzed_at && ` · ${formatFullDate(localDateOf(analysis.analyzed_at))}`}
          </p>
        </div>
        <div className="head-actions">
          <Link to={`/contracts/${contractId}`} className="btn btn-secondary">
            다시 분석
          </Link>
          {c.project_id ? (
            <Link to={`/projects/${c.project_id}`} className="btn btn-primary">
              연결된 프로젝트 →
            </Link>
          ) : (
            <Link to={`/contracts/${contractId}/project`} className="btn btn-primary">
              프로젝트 초안 만들기 →
            </Link>
          )}
        </div>
      </div>

      <section className="summary-hero" aria-label="검토 요약">
        <div>
          <p className="muted small" style={{ margin: 0 }}>
            검토 요약
          </p>
          <h2>
            {mustTalk > 0
              ? `꼭 협의할 조건이 ${mustTalk}개 있어요${needsCheck > 0 ? ` · 확인해 볼 조건이 ${needsCheck}개` : ''}`
              : needsCheck > 0
                ? `확인해 볼 조건이 ${needsCheck}개 있어요`
                : '확인이 필요한 조건이 없어요'}
          </h2>
          <p className="muted" style={{ margin: 0 }}>
            "꼭 협의"는 금액·권리처럼 중요한 항목이에요. 원문 근거를 확인하고 수정 방향을 정하세요.
          </p>
        </div>
        <dl className="summary-counts">
          <div>
            <dd>{counts.caution}</dd>
            <dt>주의</dt>
          </div>
          <div>
            <dd>{counts.needs_check}</dd>
            <dt>확인 필요</dt>
          </div>
          <div>
            <dd>{counts.confirmed}</dd>
            <dt>확인됨</dt>
          </div>
        </dl>
      </section>

      <div className="contract-layout">
        <div>
          <FilterTabs
            label="검토 결과"
            items={[
              { value: 'all', label: '전체', count: counts.total },
              { value: 'caution', label: '주의', count: counts.caution },
              { value: 'needs_check', label: '확인 필요', count: counts.needs_check },
              { value: 'confirmed', label: '확인됨', count: counts.confirmed },
            ]}
            value={filter}
            onChange={setFilter}
          />
          <div className="stack">
            {items.map((r) => (
              <ResultCard key={r.id} result={r} contractId={contractId} selected={picked.has(r.id)} onToggle={() => toggle(r.id)} />
            ))}
            {items.length === 0 && <EmptyState title="해당하는 항목이 없어요." />}
          </div>
        </div>

        <aside className="contract-side">
          <section className="card" aria-labelledby="prompt-title">
            <h2 id="prompt-title" className="card-title">
              수정 프롬프트
            </h2>
            <p className="muted" style={{ marginTop: 0 }}>
              선택한 검토 항목 {picked.size}개를 반영합니다.
            </p>
            {prompt.data ? (
              <textarea id="revision-prompt" className="input prompt-box" readOnly value={prompt.data.prompt} rows={14} />
            ) : (
              <div className="prompt-placeholder muted">항목을 고르고 프롬프트를 만들면 여기에 표시돼요.</div>
            )}
            {prompt.isError && <p className="field-error">{messageOf(prompt.error)}</p>}
            {prompt.data ? (
              <button type="button" className="btn btn-primary btn-block" onClick={() => void copy()}>
                {copied ? '복사했어요' : '프롬프트 복사'}
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-primary btn-block"
                disabled={picked.size === 0 || prompt.isPending}
                onClick={() => prompt.mutate([...picked])}
              >
                수정 프롬프트 만들기
              </button>
            )}
            <p className="muted small" style={{ marginBottom: 0 }}>
              원본 계약서는 변경되지 않습니다.
            </p>
          </section>
          <div className="notice">
            <p>AI 분석은 검토를 돕는 정보예요. 최종 조건은 원문을 보고 직접 확인하세요.</p>
          </div>
        </aside>
      </div>
    </>
  )
}
