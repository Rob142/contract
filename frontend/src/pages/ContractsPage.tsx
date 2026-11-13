import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import { contractKeys, uploadContract, useContracts, type StatusGroup } from '../api/contracts'
import { messageOf } from '../api/messages'
import { FileIcon } from '../components/icons'
import { EmptyState, FilterTabs, LoadError, Loading, ProgressBar } from '../components/ui'
import { STATUS_BADGE } from '../lib/contractStatus'
import { formatFullDate, JOB_TYPE_SHORT, localDateOf } from '../lib/format'
import { useQueryClient } from '@tanstack/react-query'

type Filter = StatusGroup | 'all'
const FILTERS: Filter[] = ['all', 'needs_review', 'processing', 'ready', 'analyzed', 'failed']
const FILTER_LABELS: Record<Filter, string> = {
  all: '전체',
  needs_review: '확인 필요',
  processing: '처리 중',
  ready: '확인 완료',
  analyzed: '분석 완료',
  failed: '실패',
}

const MAX_MB = 20

type UploadState = { name: string; progress: number } | null

/** 04 계약서 목록과 업로드 */
export function ContractsPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const filter = (FILTERS.find((f) => f === searchParams.get('group')) ?? 'all') as Filter
  const [search, setSearch] = useState(searchParams.get('q') ?? '')
  const [query, setQuery] = useState(search)
  const contracts = useContracts(filter, query)

  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [upload, setUpload] = useState<UploadState>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)

  // 검색어 입력이 멈추면 조회
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300)
    return () => clearTimeout(timer)
  }, [search])

  const startUpload = async (file: File | undefined) => {
    if (!file || upload) return
    setUploadError(null)
    // 서버가 내용으로 다시 검사하지만, 명백한 경우는 미리 알려준다
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      return setUploadError('PDF 파일만 올릴 수 있어요.')
    }
    if (file.size > MAX_MB * 1024 * 1024) return setUploadError(`파일이 너무 커요. ${MAX_MB}MB 이하만 올릴 수 있어요.`)

    setUpload({ name: file.name, progress: 0 })
    try {
      const result = await uploadContract(file, (progress) => setUpload({ name: file.name, progress }))
      void qc.invalidateQueries({ queryKey: contractKeys.all })
      const projectId = searchParams.get('project')
      navigate(`/contracts/${result.contract.id}${projectId ? `?project=${projectId}` : ''}`)
    } catch (err) {
      setUploadError(err instanceof ApiError ? messageOf(err) : '업로드하지 못했어요.')
    } finally {
      setUpload(null)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const onDrop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault()
    setDragOver(false)
    void startUpload(e.dataTransfer.files[0])
  }

  const counts = contracts.data?.counts
  const tabs = FILTERS.filter((f) => f === 'all' || f === 'needs_review' || f === 'processing' || (counts?.[f] ?? 0) > 0).map(
    (f) => ({ value: f, label: FILTER_LABELS[f], count: counts?.[f] }),
  )

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">나의 워크스페이스</p>
          <h1 className="page-title">계약서</h1>
          <p className="page-desc">원문부터 분석 결과까지, 프로젝트별 계약을 관리하세요.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => inputRef.current?.click()} disabled={!!upload}>
          + 계약서 업로드
        </button>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="visually-hidden"
        tabIndex={-1}
        onChange={(e) => void startUpload(e.target.files?.[0])}
      />

      <section
        className={dragOver ? 'dropzone is-over' : 'dropzone'}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        aria-label="계약서 업로드"
      >
        <FileIcon size={28} />
        <div className="dropzone-text">
          {upload ? (
            <>
              <strong>{upload.name} 올리는 중…</strong>
              <ProgressBar value={Math.round(upload.progress * 100)} label="업로드 진행률" />
            </>
          ) : (
            <>
              <strong>계약서 PDF를 끌어 놓거나 파일을 선택하세요</strong>
              <span className="muted">텍스트 PDF와 스캔 PDF를 모두 확인할 수 있어요. 최대 {MAX_MB}MB, 50쪽.</span>
            </>
          )}
        </div>
        <button type="button" className="btn btn-secondary" onClick={() => inputRef.current?.click()} disabled={!!upload}>
          파일 선택
        </button>
      </section>
      {uploadError && (
        <div className="alert alert-error" role="alert" style={{ marginTop: -12, marginBottom: 24 }}>
          {uploadError}
        </div>
      )}

      <div className="tabs-row">
        <FilterTabs
          label="계약서 상태"
          items={tabs}
          value={filter}
          onChange={(value) => {
            const next = new URLSearchParams(searchParams)
            if (value === 'all') next.delete('group')
            else next.set('group', value)
            setSearchParams(next, { replace: true })
          }}
        />
        <input
          className="input search-input"
          type="search"
          placeholder="계약서 또는 거래처 검색"
          aria-label="계약서 또는 거래처 검색"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <section className="card" aria-labelledby="contract-list-title">
        <div className="card-head">
          <h2 id="contract-list-title" className="card-title">
            내 계약서
          </h2>
          <span className="muted small">최근 업로드순</span>
        </div>
        {contracts.isPending ? (
          <Loading />
        ) : contracts.isError ? (
          <LoadError error={contracts.error} onRetry={() => void contracts.refetch()} />
        ) : contracts.data.items.length === 0 ? (
          <EmptyState title={query ? '검색 결과가 없어요.' : '아직 올린 계약서가 없어요.'} />
        ) : (
          <div className="table-wrap">
            <table className="table table-links">
              <thead>
                <tr>
                  <th>계약서</th>
                  <th>직업군</th>
                  <th>거래처</th>
                  <th>업로드일</th>
                  <th>상태</th>
                  <th>다음 단계</th>
                </tr>
              </thead>
              <tbody>
                {contracts.data.items.map((c) => {
                  const badge = STATUS_BADGE[c.status]
                  return (
                    <tr key={c.id}>
                      <td>
                        <Link to={`/contracts/${c.id}`} className="row-link">
                          {c.title}
                        </Link>
                        {c.page_count !== null && <span className="muted small"> · {c.page_count}쪽</span>}
                      </td>
                      <td>{JOB_TYPE_SHORT[c.job_type]}</td>
                      <td>{c.client?.name ?? <span className="muted">—</span>}</td>
                      <td>{formatFullDate(localDateOf(c.uploaded_at))}</td>
                      <td>
                        <span className={badge.className}>{badge.label}</span>
                      </td>
                      <td>
                        {c.project_id ? (
                          <Link to={`/projects/${c.project_id}`} className="link-strong">
                            프로젝트 보기
                          </Link>
                        ) : c.status === 'ready' || c.status === 'analyzed' ? (
                          <Link to={`/contracts/${c.id}/project`} className="link-strong">
                            프로젝트 만들기
                          </Link>
                        ) : c.status === 'needs_review' ? (
                          <Link to={`/contracts/${c.id}`} className="link-strong">
                            조건 확인
                          </Link>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid-2" style={{ marginTop: 24 }}>
        <section className="card">
          <h2 className="card-title">분석은 이렇게 진행돼요</h2>
          <ol className="steps">
            <li>01 PDF 업로드</li>
            <li aria-hidden="true">→</li>
            <li>02 텍스트 확인</li>
            <li aria-hidden="true">→</li>
            <li>03 AI 분석</li>
          </ol>
          <p className="muted">금액과 날짜를 먼저 확인하면 이후 프로젝트와 청구에 정확히 연결할 수 있어요.</p>
        </section>
        <section className="card">
          <h2 className="card-title">기밀을 지키는 분석 선택</h2>
          <p className="muted" style={{ margin: 0, lineHeight: 1.8 }}>
            원본은 비공개 저장소에만 보관해요. 상용 API는 외부 전송 내용을 확인한 후 실행하고,
            <br />
            로컬 LLM을 선택하면 외부 API로 자동 전환하지 않아요.
          </p>
        </section>
      </div>
    </>
  )
}
