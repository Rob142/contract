import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiError } from '../api/client'
import {
  contractFileUrl,
  isProcessing,
  useCancelJob,
  useContract,
  useContractText,
  useDeleteContract,
  useRetryExtract,
  useUpdateFields,
  type ContractDetail,
  type ContractField,
  type ContractText,
  type FieldKey,
} from '../api/contracts'
import { messageOf } from '../api/messages'
import { AmountField } from '../components/AmountField'
import { AnalysisCard } from '../components/AnalysisCard'
import { ContractSteps, isConfirmed } from '../components/ContractSteps'
import { JobTypeSelect } from '../components/JobTypeSelect'
import { UploadVersionButton } from '../components/UploadVersionButton'
import { useAnalysis } from '../api/analysis'
import { useProject } from '../api/projects'
import { forgetLinkTarget, recallLinkTarget, rememberLinkTarget } from '../lib/linkTarget'
import { TextField } from '../components/Field'
import { PaymentTermsField } from '../components/PaymentTermsField'
import { PdfViewer, type Highlight } from '../components/PdfViewer'
import { FilterTabs, LoadError, Loading } from '../components/ui'
import { FAILURE_REASONS, failureMessage, FIELD_LABELS, JOB_STAGE_LABELS, STATUS_BADGE } from '../lib/contractStatus'
import { formatFullDate, formatWon, groupDigits, localDateOf } from '../lib/format'
import { NotFoundPage } from './NotFoundPage'

type FormValues = Record<FieldKey, string>

function initialValues(fields: ContractField[]): FormValues {
  const value = (key: FieldKey) => {
    const f = fields.find((x) => x.key === key)
    return f?.confirmed_value ?? f?.extracted_value ?? ''
  }
  return {
    contract_amount: value('contract_amount'),
    final_due_date: value('final_due_date'),
    payment_terms: value('payment_terms'),
    revision_count: value('revision_count'),
  }
}

function displayValue(key: FieldKey, value: string): string {
  if (key === 'contract_amount') return formatWon(value)
  if (key === 'final_due_date') return formatFullDate(value)
  return value
}

/** 처리 중·실패 상태 카드 */
function ProcessingCard({ contract }: { contract: ContractDetail }) {
  const cancel = useCancelJob(contract.id)
  const retry = useRetryExtract(contract.id)
  const job = contract.job

  if (contract.status === 'failed') {
    return (
      <section className="card">
        <div className="card-head">
          <h2 className="card-title">텍스트 추출</h2>
          <span className="badge badge-red">실패</span>
        </div>
        <p>{failureMessage(contract.failure_reason)}</p>
        {contract.failure_reason !== 'cancelled' && !FAILURE_REASONS[contract.failure_reason ?? ''] && (
          <p className="muted small">오류 코드: {contract.failure_reason}</p>
        )}
        <button type="button" className="btn btn-primary" onClick={() => retry.mutate()} disabled={retry.isPending}>
          다시 추출
        </button>
        {retry.isError && <p className="field-error">{messageOf(retry.error)}</p>}
      </section>
    )
  }

  const running = job?.status === 'running'
  return (
    <section className="card" aria-live="polite">
      <div className="card-head">
        <h2 className="card-title">텍스트 추출 중</h2>
        <span className="spinner spinner-sm" aria-hidden="true" />
      </div>
      <p>
        {job?.cancel_requested
          ? '취소를 요청했어요. 현재 페이지가 끝나면 멈춰요.'
          : running
            ? (JOB_STAGE_LABELS[job?.stage ?? ''] ?? '처리하고 있어요')
            : '처리 순서를 기다리고 있어요.'}
      </p>
      <p className="muted small">
        다른 화면으로 이동해도 계속 처리돼요.
        {job && job.attempts > 1 && ` (재시도 ${job.attempts - 1}회)`}
      </p>
      {job && !job.cancel_requested && (
        <button type="button" className="btn btn-secondary" onClick={() => cancel.mutate(job.id)} disabled={cancel.isPending}>
          추출 취소
        </button>
      )}
      {cancel.isError && <p className="field-error">{messageOf(cancel.error)}</p>}
    </section>
  )
}

/** 분석 전 확인: 원문과 비교해 금액·납기·지급 조건을 확정한다 */
function ReviewCard({ contract, onShowEvidence }: { contract: ContractDetail; onShowEvidence: (field: ContractField) => void }) {
  const update = useUpdateFields(contract.id)
  const [values, setValues] = useState<FormValues>(() => initialValues(contract.fields))
  const [checked, setChecked] = useState(false)
  const [saved, setSaved] = useState(false)
  const confirmed = isConfirmed(contract.status)
  // 확인을 마친 뒤에는 한 줄 요약으로 접어 두고, 고칠 때만 펼친다
  const [editing, setEditing] = useState(!confirmed)
  const fieldByKey = Object.fromEntries(contract.fields.map((f) => [f.key, f])) as Partial<Record<FieldKey, ContractField>>

  const set = (key: FieldKey, value: string) => {
    setValues((v) => ({ ...v, [key]: value }))
    setSaved(false)
  }

  const missing = (['contract_amount', 'final_due_date', 'payment_terms'] as const).filter((k) => !values[k].trim())
  const payload = {
    contract_amount: values.contract_amount || null,
    final_due_date: values.final_due_date || null,
    payment_terms: values.payment_terms.trim() || null,
    revision_count: values.revision_count.trim() || null,
  }

  const onConfirm = (e: FormEvent) => {
    e.preventDefault()
    if (missing.length || !checked) return
    update.mutate(
      { values: payload, confirm: true },
      {
        onSuccess: () => {
          setSaved(true)
          setEditing(false)
        },
      },
    )
  }

  // 수정 계약서면 이전 버전에서 확인한 값을 함께 보여 준다
  const previousHint = (key: FieldKey) => {
    const prev = contract.previous_values?.[key]
    if (prev === undefined) return null
    return (
      <span className="previous-value">
        {' · '}이전 버전: <strong>{prev ? displayValue(key, prev) : '없음'}</strong>
      </span>
    )
  }
  const hint = (key: FieldKey) => {
    const field = fieldByKey[key]
    if (!field?.extracted_value) {
      return (
        <span>
          원문에서 찾지 못했어요. 직접 확인해 입력해 주세요.
          {previousHint(key)}
        </span>
      )
    }
    return (
      <span>
        원문에서 찾은 값: <strong>{displayValue(key, field.extracted_value)}</strong>
        {previousHint(key)}
        {field.evidence && (
          <>
            {' · '}
            {field.evidence.page_no}쪽{' '}
            <button type="button" className="link-button" onClick={() => onShowEvidence(field)}>
              원문 보기
            </button>
          </>
        )}
      </span>
    )
  }

  if (confirmed && !editing) {
    return (
      <section className="card" aria-labelledby="review-title">
        <div className="card-head">
          <h2 id="review-title" className="card-title">
            확인한 계약 조건
          </h2>
          <span className="badge badge-green">확인 완료</span>
        </div>
        <dl className="amount-list">
          <div>
            <dt>계약 금액</dt>
            <dd>{formatWon(fieldByKey.contract_amount?.confirmed_value)}</dd>
          </div>
          <div>
            <dt>최종 납기</dt>
            <dd>{fieldByKey.final_due_date?.confirmed_value ? formatFullDate(fieldByKey.final_due_date.confirmed_value) : '—'}</dd>
          </div>
          <div>
            <dt>수정 횟수</dt>
            <dd>{fieldByKey.revision_count?.confirmed_value ?? '계약서에 없음'}</dd>
          </div>
        </dl>
        <p className="small" style={{ margin: '0 0 12px' }}>
          <span className="muted">지급 조건 </span>
          {fieldByKey.payment_terms?.confirmed_value}
        </p>
        <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)} disabled={contract.status === 'analyzing'}>
          조건 수정
        </button>
      </section>
    )
  }

  return (
    <section className="card" aria-labelledby="review-title">
      <div className="card-head">
        <h2 id="review-title" className="card-title">
          {confirmed ? '계약 조건 수정' : '① 조건 확인'}
        </h2>
        <span className={confirmed ? 'badge badge-green' : 'badge badge-amber'}>{confirmed ? '확인 완료' : '확인 필요'}</span>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        원문과 추출된 값을 비교해 주세요. 확인한 값만 프로젝트와 청구에 쓰여요.
        {!confirmed && ' 확인을 마치면 AI 분석과 프로젝트 만들기가 열려요.'}
      </p>

      <form className="review-form" onSubmit={onConfirm} noValidate>
        <JobTypeSelect contract={contract} />

        <AmountField
          label="계약 금액"
          value={values.contract_amount}
          onChange={(v) => set('contract_amount', v)}
        />
        <p className={fieldByKey.contract_amount?.extracted_value ? 'field-hint review-hint' : 'field-hint review-hint is-missing'}>
          {hint('contract_amount')}
        </p>

        <TextField label="최종 납기" type="date" value={values.final_due_date} onChange={(e) => set('final_due_date', e.target.value)} />
        <p className={fieldByKey.final_due_date?.extracted_value ? 'field-hint review-hint' : 'field-hint review-hint is-missing'}>
          {hint('final_due_date')}
        </p>

        <PaymentTermsField
          value={values.payment_terms}
          maxLength={200}
          onChange={(value) => set('payment_terms', value)}
        />
        <p className={fieldByKey.payment_terms?.extracted_value ? 'field-hint review-hint' : 'field-hint review-hint is-missing'}>
          {hint('payment_terms')}
        </p>

        <TextField
          label="수정 횟수 (선택)"
          placeholder="원문에 없으면 비워 두세요"
          value={values.revision_count}
          maxLength={50}
          onChange={(e) => set('revision_count', e.target.value)}
        />
        <p className="field-hint review-hint">{hint('revision_count')}</p>

        <label className="checkbox">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          금액과 날짜를 원문에서 확인했습니다
        </label>

        {update.isError && (
          <div className="alert alert-error" role="alert">
            {messageOf(update.error)}
          </div>
        )}
        {saved && confirmed && (
          <div className="alert alert-success" role="status">
            확인한 값을 저장했어요.
          </div>
        )}

        <button type="submit" className="btn btn-primary btn-block" disabled={!checked || missing.length > 0 || update.isPending}>
          {update.isPending
            ? '저장 중…'
            : missing.length > 0
              ? `확인 완료 (${missing.length}개 남음)`
              : confirmed
                ? '수정한 값으로 다시 확인'
                : '확인 완료'}
        </button>
        {missing.length > 0 && (
          <p className="field-hint">
            {missing.map((k) => FIELD_LABELS[k]).join(', ')}을(를) 입력하면 확인을 마칠 수 있어요.
          </p>
        )}
        {missing.length === 0 && !checked && <p className="field-hint">원문과 비교했다면 위 확인란을 체크해 주세요.</p>}
        {confirmed && (
          <button type="button" className="btn btn-secondary btn-block" onClick={() => setEditing(false)}>
            취소
          </button>
        )}
      </form>
    </section>
  )
}

/** 추출 텍스트 보기: 페이지별 방식·품질과 줄 단위 블록. 줄을 누르면 원본 위치를 보여준다 */
function ExtractedText({ text, onPick }: { text: ContractText; onPick: (page: number, key: string) => void }) {
  return (
    <div className="extracted">
      {text.pages.map((p) => (
        <section key={p.page_no} className="extracted-page" aria-label={`${p.page_no}쪽`}>
          <header>
            <strong>{p.page_no}쪽</strong>
            <span className="badge badge-gray">{p.method === 'ocr' ? 'OCR' : '텍스트'}</span>
            {p.quality !== null && <span className="muted small">품질 {Math.round(p.quality * 100)}%</span>}
            {p.needs_review && <span className="badge badge-amber">확인 필요</span>}
          </header>
          {p.blocks.length === 0 ? (
            <p className="muted">읽은 글자가 없어요.</p>
          ) : (
            <ol>
              {p.blocks.map((b) => (
                <li key={b.key}>
                  <button type="button" onClick={() => onPick(p.page_no, b.key)}>
                    {b.text}
                  </button>
                </li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </div>
  )
}

/** 05 계약서 상세 */
export function ContractDetailPage() {
  const { contractId = '' } = useParams()
  const navigate = useNavigate()
  const contract = useContract(contractId)
  const [page, setPage] = useState(1)
  const [highlight, setHighlight] = useState<Highlight | null>(null)
  const status = contract.data?.status
  const extracting = status === 'uploaded' || status === 'extracting'
  const extracted = Boolean(status) && !extracting && status !== 'failed'
  const text = useContractText(contractId, extracted)
  // 분석 결과(06)의 "원문 보기"에서 넘어오면 해당 줄을 표시한다: ?page=1&block=p1-b004
  const [searchParams] = useSearchParams()
  const [linked, setLinked] = useState<string | null>(null)
  // 프로젝트 화면에서 출발했으면 그 프로젝트를 기억한다 (다른 메뉴에 다녀와도 유지)
  const paramTarget = searchParams.get('project')
  const [targetProjectId, setTargetProjectId] = useState<string | null>(() => paramTarget ?? recallLinkTarget(contractId))
  if (paramTarget && paramTarget !== targetProjectId) setTargetProjectId(paramTarget)
  useEffect(() => {
    if (paramTarget) rememberLinkTarget(contractId, paramTarget)
  }, [contractId, paramTarget])
  const targetProject = useProject(targetProjectId ?? '', Boolean(targetProjectId))
  const wantedBlock = searchParams.get('block')
  if (wantedBlock && text.data && linked !== wantedBlock) {
    const pageNo = Number(searchParams.get('page') ?? '1')
    const block = text.data.pages.find((p) => p.page_no === pageNo)?.blocks.find((b) => b.key === wantedBlock)
    setLinked(wantedBlock)
    setPage(pageNo)
    if (block?.bbox) setHighlight({ page: pageNo, bbox: block.bbox as Highlight['bbox'] })
  }
  const remove = useDeleteContract(contractId)
  const analysis = useAnalysis(contractId)
  const [view, setView] = useState<'pdf' | 'text'>('pdf')
  const [confirmDelete, setConfirmDelete] = useState(false)

  if (contract.isError && contract.error instanceof ApiError && contract.error.status === 404) return <NotFoundPage />
  if (contract.isPending) return <Loading />
  if (contract.isError) return <LoadError error={contract.error} onRetry={() => void contract.refetch()} />

  const c = contract.data
  // 이미 프로젝트가 있거나 연결할 수 없는 프로젝트면 안내하지 않는다
  const showTarget = Boolean(
    targetProjectId && !c.project_id && targetProject.data && !targetProject.data.has_contract && targetProject.data.status !== 'archived',
  )
  const badge = STATUS_BADGE[c.status]
  const reviewPages = c.pages.filter((p) => p.needs_review)

  const showBlock = (pageNo: number, key: string) => {
    const block = text.data?.pages.find((p) => p.page_no === pageNo)?.blocks.find((b) => b.key === key)
    setView('pdf')
    setPage(pageNo)
    setHighlight(block?.bbox ? { page: pageNo, bbox: block.bbox as Highlight['bbox'] } : null)
  }

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">
            <Link to="/contracts">계약서</Link>
          </p>
          <h1 className="page-title">{c.title}</h1>
          <p className="page-desc">
            {c.client ? `${c.client.name} · ` : ''}원본 v{c.version_no}
            {c.page_count !== null && ` · ${c.page_count}페이지`} · 업로드 {formatFullDate(localDateOf(c.uploaded_at))} ·{' '}
            {groupDigits(Math.ceil(c.file.size_bytes / 1024))}KB
          </p>
        </div>
        <div className="head-actions">
          <span className={badge.className}>{badge.label}</span>
          <a className="btn btn-secondary" href={contractFileUrl(c.id, true)}>
            원본 다운로드
          </a>
          {extracted && !extracting && <UploadVersionButton contractId={c.id} />}
        </div>
      </div>
      {(c.versions?.length ?? 0) > 1 && (
        <p className="version-line muted small">
          버전{' '}
          {c.versions?.map((v, i) => (
            <span key={v.id}>
              {i > 0 && ' · '}
              <strong className={v.version_no === c.version_no ? 'is-current' : undefined}>v{v.version_no}</strong>
              {v.version_no === c.version_no ? ' (현재 화면)' : ''}
              {v.version_no === c.project_version_no ? ' (프로젝트가 쓰는 버전)' : ''}
            </span>
          ))}
        </p>
      )}

      {showTarget && (
        <div className="notice notice-row link-target" role="status">
          <p>
            <strong>{targetProject.data?.name}</strong> 프로젝트에 연결하려고 연 계약서예요.{' '}
            {isConfirmed(c.status) ? '아래 ③에서 연결하세요.' : '조건 확인을 마치면 연결할 수 있어요.'}
          </p>
          <button
            type="button"
            className="link-button"
            onClick={() => {
              forgetLinkTarget(contractId)
              setTargetProjectId(null)
            }}
          >
            연결 안 함
          </button>
        </div>
      )}
      {extracted && (
        <ContractSteps
          contract={c}
          hasAnalysis={Boolean(analysis.data?.analysis)}
          targetProjectId={showTarget ? targetProjectId : null}
        />
      )}

      <div className="contract-layout">
        <div className="contract-main">
          {extracted && (
            <FilterTabs
              label="원본 보기 방식"
              items={[
                { value: 'pdf', label: '원본 PDF' },
                { value: 'text', label: '추출 텍스트' },
              ]}
              value={view}
              onChange={setView}
            />
          )}
          {view === 'text' && extracted ? (
            text.isPending ? (
              <Loading />
            ) : text.isError ? (
              <LoadError error={text.error} onRetry={() => void text.refetch()} />
            ) : (
              <ExtractedText text={text.data} onPick={showBlock} />
            )
          ) : (
            <PdfViewer
              url={contractFileUrl(c.id)}
              page={page}
              onPageChange={(p) => {
                setPage(p)
                setHighlight(null)
              }}
              highlight={highlight}
            />
          )}
        </div>

        <aside className="contract-side">
          {extracting || c.status === 'failed' ? (
            <ProcessingCard contract={c} />
          ) : (
            <>
              {isConfirmed(c.status) && <AnalysisCard contract={c} />}
              <ReviewCard
                key={`${c.version_id}-${isConfirmed(c.status)}`}
                contract={c}
                onShowEvidence={(field) => field.evidence && showBlock(field.evidence.page_no, field.evidence.block_key)}
              />
            </>
          )}

          {reviewPages.length > 0 && (
            <section className="card">
              <h2 className="card-title">원문과 비교가 필요한 페이지</h2>
              <ul className="row-list">
                {reviewPages.map((p) => (
                  <li key={p.page_no}>
                    <button
                      type="button"
                      className="schedule-row"
                      onClick={() => {
                        setView('pdf')
                        setPage(p.page_no)
                        setHighlight(null)
                      }}
                    >
                      <div>
                        <strong>{p.page_no}쪽</strong>
                        <span className="muted">
                          {p.method === 'ocr' ? 'OCR로 읽음' : '텍스트 품질 낮음'}
                          {p.quality !== null && ` · 인식 품질 ${Math.round(p.quality * 100)}%`}
                        </span>
                      </div>
                      <span className="badge badge-amber">확인 필요</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="card card-quiet">
            <p className="muted small" style={{ margin: 0 }}>
              원본은 비공개 저장소에만 보관되고, 본인만 열람할 수 있어요.
            </p>
            <button
              type="button"
              className="btn btn-danger-text"
              disabled={remove.isPending || isProcessing(c.status)}
              onClick={() =>
                confirmDelete
                  ? remove.mutate(undefined, { onSuccess: () => navigate('/contracts', { replace: true }) })
                  : setConfirmDelete(true)
              }
            >
              {confirmDelete ? '정말 삭제할까요? 원본과 추출 결과가 모두 지워져요' : '계약서 삭제'}
            </button>
            {remove.isError && <p className="field-error">{messageOf(remove.error)}</p>}
          </section>
        </aside>
      </div>
    </>
  )
}
