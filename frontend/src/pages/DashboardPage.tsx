import { useState } from 'react'
import { Link, useOutletContext } from 'react-router'

import type { User } from '../api/auth'
import { useDashboard, type Dashboard } from '../api/projects'
import { NewProjectDialog } from '../components/ProjectForm'
import { EmptyState, LoadError, Loading, ProgressBar } from '../components/ui'
import { daysBetween, displayName, formatMonthDay, formatShortDate, formatWon, todayLine } from '../lib/format'

const PAYMENT_STATUS: Record<Dashboard['invoices'][number]['payment_status'], string> = {
  unpaid: '미입금',
  partial: '일부 입금',
  paid: '완납',
}

type Todo = Dashboard['todos'][number]

/** 할 일의 target을 실제 화면 경로로 바꾼다 */
export function todoPath(t: Todo): string {
  switch (t.target) {
    case 'contract':
      return `/contracts/${t.target_id}`
    case 'contract_project':
      return `/contracts/${t.target_id}/project`
    case 'invoice':
      return `/invoices/${t.target_id}`
    case 'invoice_new':
      return `/invoices/new?project=${t.target_id}`
    case 'project':
      return `/projects/${t.target_id}`
    case 'project_revision':
      return `/projects/${t.target_id}/revise`
  }
}

const TODO_BADGE: Record<Todo['tone'], string> = {
  warning: 'badge badge-red',
  action: 'badge badge-green',
  info: 'badge badge-gray',
}
const TODO_LABEL: Record<Todo['tone'], string> = { warning: '급해요', action: '할 일', info: '추천' }

function TodoCard({ todos }: { todos: Todo[] }) {
  return (
    <section className="card todo-card" aria-labelledby="todo-title">
      <div className="card-head">
        <h2 id="todo-title" className="card-title">
          지금 할 일
        </h2>
        {todos.length > 0 && <span className="muted small">{todos.length}건</span>}
      </div>
      {todos.length === 0 ? (
        <EmptyState title="밀린 일이 없어요.">
          <Link to="/contracts" className="btn btn-secondary">
            새 계약서 올리기
          </Link>
        </EmptyState>
      ) : (
        <ul className="row-list">
          {todos.map((t) => (
            <li key={`${t.kind}-${t.target_id}-${t.title}`}>
              <Link to={todoPath(t)} className="todo-row">
                <span className={TODO_BADGE[t.tone]}>{TODO_LABEL[t.tone]}</span>
                <div>
                  <strong>{t.title}</strong>
                  <span className="muted">
                    {t.detail}
                    {t.due_date && ` · ${formatShortDate(t.due_date)}`}
                  </span>
                </div>
                <span className="todo-arrow" aria-hidden="true">
                  →
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** 누르면 숫자의 근거가 되는 목록으로 이동한다 */
function Kpi({ label, value, sub, to }: { label: string; value: string; sub: string; to: string }) {
  return (
    <Link to={to} className="card kpi kpi-link" aria-label={`${label} ${value} — 자세히 보기`}>
      <p className="kpi-label">
        {label}
        <span className="kpi-arrow" aria-hidden="true">
          →
        </span>
      </p>
      <p className="kpi-value">{value}</p>
      <p className="kpi-sub">{sub}</p>
    </Link>
  )
}


/** 03 통합 대시보드 */
export function DashboardPage() {
  const user = useOutletContext<User>()
  const dashboard = useDashboard()
  const [creating, setCreating] = useState(false)

  const head = (
    <div className="page-head">
      <div>
        <p className="page-eyebrow">나의 워크스페이스</p>
        <h1 className="page-title">안녕하세요, {displayName(user.name)}님</h1>
        <p className="page-desc">{todayLine()} 이번 주 업무를 확인하세요.</p>
      </div>
      <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
        새 프로젝트
      </button>
    </div>
  )

  const dialog = creating && <NewProjectDialog defaultJobType={user.job_type} onClose={() => setCreating(false)} />

  if (!dashboard.isSuccess) {
    return (
      <>
        {head}
        {dashboard.isError ? (
          <LoadError error={dashboard.error} onRetry={() => void dashboard.refetch()} />
        ) : (
          <Loading />
        )}
        {dialog}
      </>
    )
  }

  const d = dashboard.data

  return (
    <>
      {head}

      <TodoCard todos={d.todos} />

      <div className="kpi-grid">
        <Kpi
          label="진행 중 프로젝트"
          value={`${d.active_projects}개`}
          sub={`이번 달 완료 작업 ${d.tasks_completed_this_month}개`}
          to="/projects?status=active"
        />
        <Kpi
          label="이번 주 마감 작업"
          value={`${d.tasks_due_this_week}개`}
          sub={d.nearest_due_date ? `가장 가까운 마감 ${formatMonthDay(d.nearest_due_date)}` : '예정된 마감이 없어요'}
          to={d.upcoming[0] ? `/projects/${d.upcoming[0].project_id}?tab=schedule` : '/projects?status=active'}
        />
        <Kpi
          label="이번 달 수입"
          value={formatWon(d.received_this_month)}
          sub={`입금일 기준 · 발행 청구액 ${formatWon(d.billed_this_month)}`}
          to="/settlement"
        />
        <Kpi
          label="미수액"
          value={formatWon(d.outstanding_total)}
          sub={`누적 입금액 ${formatWon(d.paid_total)}`}
          to="/invoices?group=outstanding"
        />
      </div>

      <div className="dashboard-grid">
        <section className="card" aria-labelledby="active-projects">
          <div className="card-head">
            <h2 id="active-projects" className="card-title">
              진행 중인 프로젝트
            </h2>
            <Link to="/projects" className="link-strong">
              전체 보기 →
            </Link>
          </div>
          {d.projects.length === 0 ? (
            <EmptyState title="진행 중인 프로젝트가 없어요.">
              <button type="button" className="btn btn-secondary" onClick={() => setCreating(true)}>
                새 프로젝트 만들기
              </button>
            </EmptyState>
          ) : (
            <ul className="row-list">
              {d.projects.map((p) => (
                <li key={p.id}>
                  <Link to={`/projects/${p.id}`} className="project-row">
                    <div className="project-row-head">
                      <div>
                        <strong>{p.name}</strong>
                        <span className="muted">
                          {p.client.name} · 계약 금액 {formatWon(p.contract_amount)}
                        </span>
                      </div>
                      {p.due_date && <span className="badge badge-gray">{formatMonthDay(p.due_date)} 마감</span>}
                    </div>
                    <div className="progress-row">
                      <ProgressBar value={p.progress_pct} label={`${p.name} 진행률`} />
                      <span className="muted">{p.progress_pct === null ? '산정 전' : `${p.progress_pct}%`}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="card" aria-labelledby="upcoming">
          <h2 id="upcoming" className="card-title">
            다가오는 일정
          </h2>
          {d.upcoming.length === 0 ? (
            <EmptyState title="마감일이 정해진 작업이 없어요." />
          ) : (
            <ul className="row-list">
              {d.upcoming.map((t) => {
                const soon = daysBetween(d.today, t.due_date) <= 2
                return (
                  <li key={t.task_id}>
                    <Link to={`/projects/${t.project_id}`} className="schedule-row">
                      <div>
                        <strong>{t.title}</strong>
                        <span className="muted">{t.project_name}</span>
                      </div>
                      <span className={soon ? 'badge badge-amber' : 'badge badge-gray'}>{formatShortDate(t.due_date)}</span>
                    </Link>
                  </li>
                )
              })}
            </ul>
          )}
          <div className="notice" style={{ marginTop: 16 }}>
            <p>
              {d.tasks_due_today > 0
                ? `오늘 마감인 작업이 ${d.tasks_due_today}개 있어요.`
                : '오늘 마감인 작업은 없어요.'}
            </p>
          </div>
        </section>
      </div>

      <section className="card" aria-labelledby="billing" style={{ marginTop: 24 }}>
        <div className="card-head">
          <h2 id="billing" className="card-title">
            청구와 입금 현황
          </h2>
          <Link to="/invoices" className="link-strong">
            전체 보기 →
          </Link>
        </div>
        {d.invoices.length === 0 ? (
          <EmptyState title="미수금이 남은 인보이스가 없어요." />
        ) : (
          <div className="table-wrap">
            <table className="table table-links">
              <thead>
                <tr>
                  <th>인보이스</th>
                  <th>거래처</th>
                  <th className="num">청구 금액</th>
                  <th className="num">입금 금액</th>
                  <th>상태</th>
                </tr>
              </thead>
              <tbody>
                {d.invoices.map((inv) => (
                  <tr key={inv.invoice_id}>
                    <td>
                      <Link to={`/invoices/${inv.invoice_id}`} className="row-link">
                        {inv.invoice_no} · {inv.title}
                      </Link>
                    </td>
                    <td>
                      <Link to={`/projects/${inv.project_id}`} className="muted-link">
                        {inv.client_name}
                      </Link>
                    </td>
                    <td className="num">{formatWon(inv.total)}</td>
                    <td className="num">{formatWon(inv.paid_amount)}</td>
                    <td>
                      {inv.is_overdue ? (
                        <span className="badge badge-red">연체</span>
                      ) : (
                        <span className={inv.payment_status === 'partial' ? 'badge badge-amber' : 'badge badge-gray'}>
                          {PAYMENT_STATUS[inv.payment_status]}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {dialog}
    </>
  )
}
