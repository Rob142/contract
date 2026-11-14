import { AttachmentsCard, FeedbackCard, RevisionCard, ShareCard } from '../components/ProjectSharePanels'
import { useState } from 'react'
import { Link, useOutletContext, useParams, useSearchParams } from 'react-router'

import type { User } from '../api/auth'
import { ApiError } from '../api/client'
import { useContract, useContracts } from '../api/contracts'
import { useInvoices } from '../api/invoices'
import { messageOf } from '../api/messages'
import {
  useProject,
  useTasks,
  useUnlinkContract,
  useUpdateProject,
  type ProjectDetail,
  type Task,
  type TaskStatus,
} from '../api/projects'
import { Dialog } from '../components/Dialog'
import { KanbanBoard } from '../components/KanbanBoard'
import { UploadVersionButton } from '../components/UploadVersionButton'
import { EditProjectDialog } from '../components/ProjectForm'
import { TaskDialog, STATUS_LABELS } from '../components/TaskDialog'
import { EmptyState, FilterTabs, LoadError, Loading } from '../components/ui'
import { FileIcon } from '../components/icons'
import { formatFullDate, formatMonthDay, formatShortDate, formatWon, todayIso } from '../lib/format'
import { invoiceBadge } from '../lib/invoiceStatus'
import { NotFoundPage } from './NotFoundPage'

type Tab = 'kanban' | 'schedule'

const PROJECT_STATUS: Record<ProjectDetail['status'], { label: string; className: string }> = {
  active: { label: '진행 중', className: 'badge badge-green' },
  completed: { label: '완료', className: 'badge badge-gray' },
  archived: { label: '보관', className: 'badge badge-gray' },
}

function paymentTermsText(project: ProjectDetail): string {
  if (project.payment_terms.length === 0) return project.has_contract ? '확인된 지급 조건 없음' : '연결된 계약 없음'
  return project.payment_terms.map((t) => t.label).join(' · ')
}

const BILLING_BADGE: Record<ProjectDetail['payment_terms'][number]['billing_status'], { label: string; className: string }> = {
  unbilled: { label: '청구 전', className: 'badge badge-gray' },
  draft: { label: '초안 작성 중', className: 'badge badge-amber' },
  billed: { label: '청구됨', className: 'badge badge-info' },
  paid: { label: '입금 완료', className: 'badge badge-green' },
}

const BOARD_KEY = 'fh.project.boardOpen'
function loadBoardOpen(): boolean {
  try {
    return localStorage.getItem(BOARD_KEY) !== 'false'
  } catch {
    return true
  }
}
function saveBoardOpen(open: boolean) {
  try {
    localStorage.setItem(BOARD_KEY, String(open))
  } catch {
    // 저장하지 못해도 동작에는 영향 없음
  }
}

/** 확인을 마쳤고 아직 어느 프로젝트에도 쓰지 않은 계약서를 골라 연결하거나, 새로 올린다 */
function LinkContractDialog({
  projectId,
  replacing = false,
  onClose,
}: {
  projectId: string
  /** 이미 계약서가 있는 프로젝트에서 수정 계약서 등으로 바꾸는 경우 */
  replacing?: boolean
  onClose: () => void
}) {
  const contracts = useContracts('all', '')
  const items = (contracts.data?.items ?? []).filter((c) => !c.project_id && c.status !== 'failed')
  const usable = items.filter((c) => c.status === 'ready' || c.status === 'analyzed')
  const pending = items.filter((c) => !(c.status === 'ready' || c.status === 'analyzed'))

  return (
    <Dialog
      open
      onClose={onClose}
      title={replacing ? '계약서 교체' : '계약서 연결'}
      footer={
        <>
          <span className="spacer" />
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            닫기
          </button>
          <Link to={`/contracts?project=${projectId}`} className="btn btn-primary">
            새 계약서 올리기
          </Link>
        </>
      }
    >
      {contracts.isPending ? (
        <Loading />
      ) : items.length === 0 ? (
        <p className="muted" style={{ margin: 0 }}>
          {replacing ? '바꿀 수 있는 계약서가 없어요. 수정 계약서를 새로 올려 주세요.' : '연결할 수 있는 계약서가 없어요.'} 새 계약서를 올리면
          조건 확인 후 이 프로젝트에 연결할 수 있어요.
        </p>
      ) : (
        <ul className="row-list">
          {usable.map((c) => (
            <li key={c.id}>
              <Link to={`/contracts/${c.id}/project?project=${projectId}`} className="schedule-row">
                <div>
                  <strong>{c.title}</strong>
                  <span className="muted">조건 확인 완료 · {replacing ? '이 계약서로 바꿀 수 있어요' : '연결할 수 있어요'}</span>
                </div>
                <span className="link-strong">{replacing ? '교체 →' : '연결 →'}</span>
              </Link>
            </li>
          ))}
          {pending.map((c) => (
            <li key={c.id}>
              <Link to={`/contracts/${c.id}?project=${projectId}`} className="schedule-row">
                <div>
                  <strong>{c.title}</strong>
                  <span className="muted">조건 확인을 먼저 마쳐야 해요</span>
                </div>
                <span className="link-strong">확인하러 가기 →</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}

/** 모든 작업을 마친 진행 중 프로젝트에 완료 처리를 제안한다. 아직 청구하지 않은 금액이 있으면 함께 알린다 */
function CompleteBanner({ project }: { project: ProjectDetail }) {
  const invoices = useInvoices('all', '', project.id)
  const update = useUpdateProject(project.id)
  if (project.status !== 'active' || project.total_tasks === 0 || project.done_tasks < project.total_tasks) return null

  const hasTerms = project.payment_terms.length > 0
  const unbilledTerms = project.payment_terms.filter((t) => t.billing_status === 'unbilled').length
  const billed = (invoices.data?.items ?? [])
    .filter((i) => i.status !== 'cancelled')
    .reduce((sum, i) => sum + Number(i.total), 0)
  const remaining = Number(project.contract_amount) - billed
  const unbilledText = hasTerms
    ? unbilledTerms > 0
      ? `아직 청구하지 않은 지급 단계가 ${unbilledTerms}개 있어요.`
      : null
    : invoices.isSuccess && remaining > 0
      ? `계약 금액 중 ${formatWon(remaining)}은 아직 청구하지 않았어요.`
      : null

  return (
    <div className="complete-banner" role="status">
      <div>
        <p>
          <strong>모든 작업을 마쳤어요.</strong> 프로젝트를 완료 처리할까요?
        </p>
        {unbilledText && <p className="muted small">{unbilledText} 완료 처리 전에 청구를 확인해 보세요.</p>}
        {update.isError && <p className="field-error">{messageOf(update.error)}</p>}
      </div>
      <div className="head-actions">
        {unbilledText && (
          <Link to={`/invoices/new?project=${project.id}`} className="btn btn-secondary">
            인보이스 작성
          </Link>
        )}
        <button
          type="button"
          className="btn btn-primary"
          disabled={update.isPending}
          onClick={() => update.mutate({ status: 'completed', version: project.version })}
        >
          프로젝트 완료 처리
        </button>
      </div>
    </div>
  )
}

/** 계약 지급 단계마다 청구 상태와 다음 행동(청구하기 / 인보이스 보기) */
function BillingStages({
  project,
  onLinkContract,
  onReplaceContract,
}: {
  project: ProjectDetail
  onLinkContract: () => void
  onReplaceContract: () => void
}) {
  const invoices = useInvoices('all', '', project.id)
  const unlink = useUnlinkContract(project.id)
  const [confirmUnlink, setConfirmUnlink] = useState(false)
  // 초안까지 청구로 본다. 취소된 청구는 서버가 다시 확인한다
  const billed = project.payment_terms.some((t) => t.billing_status !== 'unbilled' || t.carried_amount !== '0')
  // 같은 계약의 새 버전을 올렸지만 아직 반영하지 않았는지
  const contract = useContract(project.contract_id ?? '')
  const c = contract.data
  const pending =
    c && c.project_version_no !== null && c.project_version_no !== undefined && c.version_no > c.project_version_no ? c : null
  const pendingReady = pending && (pending.status === 'ready' || pending.status === 'analyzed')
  const list = invoices.data?.items ?? []

  return (
    <div className="grid-2 project-money">
      <section className="card" aria-labelledby="stages-title">
        <div className="card-head">
          <h2 id="stages-title" className="card-title">
            지급 단계
          </h2>
          {project.contract_id && (
            <Link to={`/contracts/${project.contract_id}`} className="link-strong">
              계약서 보기 →
            </Link>
          )}
        </div>
        {pending && (
          <div className="notice notice-row revision-pending" role="status">
            <p>
              수정 계약서 v{pending.version_no}을(를) 올렸어요.{' '}
              {pendingReady ? '청구 이력을 이어 붙여 프로젝트에 반영하세요.' : '조건 확인을 마치면 반영할 수 있어요.'}
            </p>
            {pendingReady ? (
              <Link to={`/projects/${project.id}/revise?version=${pending.version_id}`} className="btn btn-primary btn-sm">
                수정 계약 반영
              </Link>
            ) : (
              <Link to={`/contracts/${pending.id}`} className="btn btn-secondary btn-sm">
                조건 확인
              </Link>
            )}
          </div>
        )}
        {project.contract_id && (
          <div className="contract-manage">
            {!pending && (
              <>
                <UploadVersionButton contractId={project.contract_id} className="link-button" />
                <span aria-hidden="true">·</span>
              </>
            )}
            <button type="button" className="link-button" onClick={onReplaceContract} disabled={billed}>
              계약서 교체
            </button>
            <span aria-hidden="true">·</span>
            <button type="button" className="link-button" onClick={() => setConfirmUnlink(true)} disabled={billed}>
              연결 해제
            </button>
            {billed && (
              <span className="muted small">
                {project.payment_terms.some((t) => t.billing_status === 'billed' || t.billing_status === 'paid')
                  ? '· 청구 이력이 있어 교체·해제 대신 "수정 계약서 올리기"를 쓰세요'
                  : '· 인보이스 초안이 있어 바꿀 수 없어요 (초안을 지우면 바꿀 수 있어요)'}
              </span>
            )}
          </div>
        )}
        {unlink.isError && (
          <div className="alert alert-error" role="alert" style={{ marginBottom: 12 }}>
            {messageOf(unlink.error)}
          </div>
        )}
        {confirmUnlink && (
          <Dialog
            open
            onClose={() => setConfirmUnlink(false)}
            title="계약서 연결 해제"
            footer={
              <>
                <span className="spacer" />
                <button type="button" className="btn btn-secondary" onClick={() => setConfirmUnlink(false)}>
                  취소
                </button>
                <button
                  type="button"
                  className="btn btn-danger"
                  disabled={unlink.isPending}
                  onClick={() => unlink.mutate(undefined, { onSettled: () => setConfirmUnlink(false) })}
                >
                  {unlink.isPending ? '해제 중…' : '연결 해제'}
                </button>
              </>
            }
          >
            <p style={{ margin: 0 }}>
              프로젝트에서 계약서와 지급 단계가 빠져요. 작업과 계약서 자체는 그대로 남고, 계약서는 다른 프로젝트에 다시 연결할 수 있어요.
            </p>
          </Dialog>
        )}
        {project.payment_terms.length === 0 ? (
          <EmptyState title={project.has_contract ? '확인된 지급 조건이 없어요.' : '계약서와 연결되지 않은 프로젝트예요.'}>
            {!project.has_contract && (
              <button type="button" className="btn btn-primary" onClick={onLinkContract}>
                계약서 연결
              </button>
            )}
          </EmptyState>
        ) : (
          <ul className="row-list">
            {project.payment_terms.map((t) => {
              const badge = BILLING_BADGE[t.billing_status]
              return (
                <li key={t.id} className="stage-row">
                  <div>
                    <strong>
                      {t.label} · {formatWon(t.amount)}
                    </strong>
                    <span className="muted small">
                      {t.requirement ?? '지급 요건 없음'}
                      {t.due_date && ` · ${formatShortDate(t.due_date)}`}
                    </span>
                    {t.carried_amount !== '0' && (
                      <span className="carried small">이전 계약에서 이월 {formatWon(t.carried_amount)}</span>
                    )}
                  </div>
                  <span className={badge.className}>{badge.label}</span>
                  {t.billing_status === 'unbilled' ? (
                    <Link to={`/invoices/new?project=${project.id}`} className="btn btn-secondary btn-sm">
                      청구하기
                    </Link>
                  ) : (
                    t.invoice_id && (
                      <Link to={`/invoices/${t.invoice_id}`} className="btn btn-secondary btn-sm">
                        인보이스
                      </Link>
                    )
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="card" aria-labelledby="project-invoices-title">
        <div className="card-head">
          <h2 id="project-invoices-title" className="card-title">
            이 프로젝트의 인보이스
          </h2>
          {list.length > 0 && (
            <Link to={`/invoices?project=${project.id}`} className="link-strong">
              전체 보기 →
            </Link>
          )}
        </div>
        {invoices.isPending ? (
          <Loading />
        ) : list.length === 0 ? (
          <EmptyState title="아직 청구한 내역이 없어요.">
            <Link to={`/invoices/new?project=${project.id}`} className="btn btn-secondary">
              인보이스 작성
            </Link>
          </EmptyState>
        ) : (
          <ul className="row-list">
            {list.slice(0, 5).map((inv) => {
              const badge = invoiceBadge(inv)
              return (
                <li key={inv.id}>
                  <Link to={`/invoices/${inv.id}`} className="schedule-row">
                    <div>
                      <strong>
                        {inv.invoice_no ?? '작성 중'} · {inv.title}
                      </strong>
                      <span className="muted">
                        {formatWon(inv.total)}
                        {inv.status === 'issued' && Number(inv.balance) > 0 && ` · 잔액 ${formatWon(inv.balance)}`}
                      </span>
                    </div>
                    <span className={badge.className}>{badge.label}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
        <dl className="amount-list" style={{ marginTop: 12 }}>
          <div>
            <dt>청구</dt>
            <dd>{formatWon(project.billed_amount)}</dd>
          </div>
          <div>
            <dt>입금</dt>
            <dd>{formatWon(project.paid_amount)}</dd>
          </div>
          <div>
            <dt>미수</dt>
            <dd>{formatWon(project.outstanding_amount)}</dd>
          </div>
        </dl>
      </section>
    </div>
  )
}

/** 일정 탭: 마감일 순 목록 */
function ScheduleList({ tasks, onOpen }: { tasks: Task[]; onOpen: (id: string) => void }) {
  const dated = tasks.filter((t) => t.due_date).sort((a, b) => a.due_date!.localeCompare(b.due_date!))
  const undated = tasks.filter((t) => !t.due_date)
  if (tasks.length === 0) return <EmptyState title="아직 작업이 없어요." />

  const row = (t: Task) => (
    <li key={t.id}>
      <button type="button" className="schedule-row" onClick={() => onOpen(t.id)}>
        <div>
          <strong className={t.status === 'done' ? 'is-done' : undefined}>{t.title}</strong>
          <span className="muted">{STATUS_LABELS[t.status]}</span>
        </div>
        <span className="badge badge-gray">{t.due_date ? formatShortDate(t.due_date) : '미정'}</span>
      </button>
    </li>
  )

  return (
    <div className="card">
      <ul className="row-list">{dated.map(row)}</ul>
      {undated.length > 0 && (
        <>
          <h3 className="list-subhead">마감일 없음</h3>
          <ul className="row-list">{undated.map(row)}</ul>
        </>
      )}
    </div>
  )
}

/** 09 프로젝트 상세 (칸반) */
export function ProjectDetailPage() {
  const user = useOutletContext<User>()
  const { projectId = '' } = useParams()
  const project = useProject(projectId)
  const tasks = useTasks(projectId)
  const [searchParams] = useSearchParams()
  const [tab, setTab] = useState<Tab>(searchParams.get('tab') === 'schedule' ? 'schedule' : 'kanban')
  const [editing, setEditing] = useState(false)
  const [addingTo, setAddingTo] = useState<TaskStatus | null>(null)
  const [openTaskId, setOpenTaskId] = useState<string | null>(null)
  const [linkingContract, setLinkingContract] = useState<'link' | 'replace' | null>(null)
  const [boardOpen, setBoardOpen] = useState(loadBoardOpen)
  const toggleBoard = () => {
    setBoardOpen((v) => {
      saveBoardOpen(!v)
      return !v
    })
  }

  if (project.isError && project.error instanceof ApiError && project.error.status === 404) return <NotFoundPage />
  if (project.isPending) return <Loading />
  if (project.isError) return <LoadError error={project.error} onRetry={() => void project.refetch()} />

  const p = project.data
  const status = PROJECT_STATUS[p.status]
  const period =
    p.start_date || p.due_date
      ? `${p.start_date ? formatFullDate(p.start_date) : '시작일 미정'} — ${p.due_date ? formatShortDate(p.due_date) : '납기 미정'}`
      : '기간 미정'
  const openTask = tasks.data?.find((t) => t.id === openTaskId)

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">
            <Link to="/projects">프로젝트</Link> / {p.client.name}
          </p>
          <h1 className="page-title">{p.name}</h1>
          <p className="page-desc">
            {p.client.name} · {period} · 계약 금액 {formatWon(p.contract_amount)}
          </p>
        </div>
        <div className="head-actions">
          {p.contract_id ? (
            <Link to={`/contracts/${p.contract_id}`} className="btn btn-secondary">
              계약서
            </Link>
          ) : (
            <button type="button" className="btn btn-secondary" onClick={() => setLinkingContract('link')}>
              계약서 연결
            </button>
          )}
          <button type="button" className="btn btn-secondary" onClick={() => setEditing(true)}>
            프로젝트 수정
          </button>
          <Link to={`/invoices/new?project=${p.id}`} className="btn btn-primary">
            인보이스 작성
          </Link>
        </div>
      </div>

      <div className="summary-bar">
        <span className={status.className}>{status.label}</span>
        <span>
          <span className="muted">작업 완료</span>{' '}
          <strong>
            {p.done_tasks} / {p.total_tasks}
          </strong>
        </span>
        <span>
          <span className="muted">최종 납기</span> <strong>{p.due_date ? formatMonthDay(p.due_date) : '미정'}</strong>
        </span>
        <span>
          <span className="muted">계약 지급 조건</span> <strong>{paymentTermsText(p)}</strong>
        </span>
        <span>
          <span className="muted">미수액</span> <strong>{formatWon(p.outstanding_amount)}</strong>
        </span>
      </div>

      <CompleteBanner project={p} />

      <div className="tabs-row">
        <FilterTabs
          label="프로젝트 보기"
          items={[
            { value: 'kanban', label: '칸반' },
            { value: 'schedule', label: '일정' },
          ]}
          value={tab}
          onChange={setTab}
        />
        <div className="head-actions">
          <button type="button" className="btn btn-secondary" aria-expanded={boardOpen} onClick={toggleBoard}>
            {boardOpen ? '접기 ▴' : '펼치기 ▾'}
          </button>
          {tab === 'kanban' && boardOpen && (
            <button type="button" className="btn btn-secondary" onClick={() => setAddingTo('todo')}>
              + 작업 추가
            </button>
          )}
        </div>
      </div>

      {!boardOpen ? (
        <button type="button" className="board-collapsed" onClick={toggleBoard}>
          {tasks.data
            ? (['todo', 'doing', 'done'] as const)
                .map((s) => `${STATUS_LABELS[s]} ${tasks.data.filter((t) => t.status === s).length}`)
                .join(' · ')
            : '작업'}
          <span className="muted"> — 눌러서 펼치기</span>
        </button>
      ) : tasks.isPending ? (
        <Loading />
      ) : tasks.isError ? (
        <LoadError error={tasks.error} onRetry={() => void tasks.refetch()} />
      ) : tab === 'kanban' ? (
        <KanbanBoard
          projectId={p.id}
          tasks={tasks.data}
          user={user}
          today={todayIso()}
          addingTo={addingTo}
          setAddingTo={setAddingTo}
        />
      ) : (
        <ScheduleList tasks={tasks.data} onOpen={setOpenTaskId} />
      )}

      <BillingStages
        project={p}
        onLinkContract={() => setLinkingContract('link')}
        onReplaceContract={() => setLinkingContract('replace')}
      />
      {linkingContract && (
        <LinkContractDialog projectId={p.id} replacing={linkingContract === 'replace'} onClose={() => setLinkingContract(null)} />
      )}

      <div className="stack" style={{ marginTop: 24 }}>
        <ShareCard projectId={p.id} />
        <AttachmentsCard projectId={p.id} tasks={tasks.data ?? []} />
        <RevisionCard projectId={p.id} included={p.included_revisions ?? null} />
        <FeedbackCard projectId={p.id} tasks={tasks.data ?? []} />
      </div>

      <div className="notice notice-row" style={{ marginTop: 24 }}>
        <FileIcon size={18} />
        <p>작업을 완료해도 인보이스가 자동 발행되지는 않아요. 지급 단계의 요건을 확인한 뒤 &lsquo;청구하기&rsquo;를 눌러 주세요.</p>
      </div>

      {editing && <EditProjectDialog project={p} onClose={() => setEditing(false)} />}
      {openTask && <TaskDialog key={openTask.id} task={openTask} onClose={() => setOpenTaskId(null)} />}
    </>
  )
}
