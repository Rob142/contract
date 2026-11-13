import { useState } from 'react'
import { Link, useOutletContext, useSearchParams } from 'react-router'

import type { User } from '../api/auth'
import { useProjects, type ProjectStatus, type ProjectSummary } from '../api/projects'
import { NewProjectDialog } from '../components/ProjectForm'
import { EmptyState, FilterTabs, LoadError, Loading, ProgressBar } from '../components/ui'
import { formatMonthDay, formatShortDate, formatWon, JOB_TYPE_SHORT, todayIso } from '../lib/format'

type Filter = ProjectStatus | 'all'
const FILTERS: Filter[] = ['all', 'active', 'completed', 'archived']
const FILTER_LABELS: Record<Filter, string> = { all: '전체', active: '진행 중', completed: '완료', archived: '보관' }

function ProjectCard({ project }: { project: ProjectSummary }) {
  return (
    <article className="card project-card">
      <div className="project-card-top">
        <span className="badge badge-gray">{JOB_TYPE_SHORT[project.job_type]}</span>
        {project.status !== 'active' && (
          <span className="badge badge-green">{FILTER_LABELS[project.status]}</span>
        )}
      </div>
      <h2 className="project-card-title">{project.name}</h2>
      <p className="muted">{project.client.name}</p>

      <div className="project-card-progress">
        <div className="between">
          <span className="muted">작업 진행률</span>
          <strong className="pct">{project.progress_pct === null ? '산정 전' : `${project.progress_pct}%`}</strong>
        </div>
        <ProgressBar value={project.progress_pct} label={`${project.name} 진행률`} />
        <div className="between muted small">
          <span>
            완료 작업 {project.done_tasks} / {project.total_tasks}
          </span>
          <span>{project.due_date ? `마감 ${formatMonthDay(project.due_date)}` : '마감일 미정'}</span>
        </div>
      </div>

      <dl className="money-box">
        <div>
          <dt>계약 금액</dt>
          <dd>{formatWon(project.contract_amount)}</dd>
        </div>
        <div>
          <dt>미수액</dt>
          <dd>{formatWon(project.outstanding_amount)}</dd>
        </div>
      </dl>

      <Link to={`/projects/${project.id}`} className="btn btn-secondary btn-block">
        프로젝트 열기 →
      </Link>
    </article>
  )
}

const BAR_COLORS = ['bar-green', 'bar-blue', 'bar-amber']

/** 이번 달 일정: 진행 중 프로젝트의 시작일~납기를 이번 달 범위로 잘라 막대로 그린다. */
function MonthTimeline({ projects }: { projects: ProjectSummary[] }) {
  const today = todayIso()
  const [y, m] = today.split('-').map(Number) as [number, number]
  const daysInMonth = new Date(y, m, 0).getDate()
  const monthStart = `${today.slice(0, 7)}-01`
  const monthEnd = `${today.slice(0, 7)}-${String(daysInMonth).padStart(2, '0')}`
  const ticks = [1, 8, 15, 22, 29].filter((d) => d <= daysInMonth)
  const pos = (iso: string) => ((Number(iso.slice(8, 10)) - 1) / daysInMonth) * 100

  const rows = projects
    .filter((p) => p.status === 'active' && (p.start_date || p.due_date))
    .map((p) => ({ p, start: p.start_date ?? p.due_date!, end: p.due_date ?? p.start_date! }))
    .filter(({ start, end }) => start <= monthEnd && end >= monthStart)

  return (
    <section className="card" aria-labelledby="timeline-title" style={{ marginTop: 24 }}>
      <div className="card-head">
        <h2 id="timeline-title" className="card-title">
          이번 달 프로젝트 일정
        </h2>
        <span className="muted">
          {y}년 {m}월
        </span>
      </div>
      {rows.length === 0 ? (
        <EmptyState title="이번 달에 걸친 진행 중 프로젝트가 없어요." />
      ) : (
        <div className="timeline">
          <div className="timeline-row timeline-axis" aria-hidden="true">
            <span className="muted small">프로젝트</span>
            <div className="timeline-track">
              {ticks.map((d) => (
                <span key={d} className="timeline-tick" style={{ left: `${((d - 1) / daysInMonth) * 100}%` }}>
                  {d}일
                </span>
              ))}
              <span className="timeline-today" style={{ left: `${pos(today)}%` }} />
            </div>
          </div>
          {rows.map(({ p, start, end }, i) => {
            const from = start < monthStart ? monthStart : start
            const to = end > monthEnd ? monthEnd : end
            const left = pos(from)
            const width = Math.max(pos(to) - left + 100 / daysInMonth, 100 / daysInMonth)
            return (
              <div key={p.id} className="timeline-row">
                <Link to={`/projects/${p.id}`} className="timeline-name">
                  {p.name}
                </Link>
                <div className="timeline-track">
                  <span
                    className={`timeline-bar ${BAR_COLORS[i % BAR_COLORS.length]}`}
                    style={{ left: `${left}%`, width: `${width}%` }}
                    title={`${start} ~ ${end}`}
                  >
                    {formatShortDate(start)} → {formatShortDate(end)}
                  </span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

/** 08 프로젝트 목록 */
export function ProjectsPage() {
  const user = useOutletContext<User>()
  const [searchParams, setSearchParams] = useSearchParams()
  const filter = (FILTERS.find((f) => f === searchParams.get('status')) ?? 'active') as Filter
  const projects = useProjects(filter)
  const [creating, setCreating] = useState(false)

  const counts = projects.data?.counts
  const tabs = FILTERS.filter((f) => f !== 'archived' || (counts?.archived ?? 0) > 0).map((f) => ({
    value: f,
    label: FILTER_LABELS[f],
    count: counts?.[f],
  }))

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">나의 워크스페이스</p>
          <h1 className="page-title">프로젝트</h1>
          <p className="page-desc">여러 프로젝트의 진행 상황과 일정을 한곳에서 관리하세요.</p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
          + 새 프로젝트
        </button>
      </div>

      <FilterTabs
        label="프로젝트 상태"
        items={tabs}
        value={filter}
        onChange={(value) => setSearchParams(value === 'active' ? {} : { status: value }, { replace: true })}
      />

      {projects.isPending ? (
        <Loading />
      ) : projects.isError ? (
        <LoadError error={projects.error} onRetry={() => void projects.refetch()} />
      ) : projects.data.items.length === 0 ? (
        <div className="card">
          <EmptyState title={filter === 'active' ? '진행 중인 프로젝트가 없어요.' : '해당하는 프로젝트가 없어요.'}>
            <button type="button" className="btn btn-secondary" onClick={() => setCreating(true)}>
              새 프로젝트 만들기
            </button>
          </EmptyState>
        </div>
      ) : (
        <>
          <div className="project-grid">
            {projects.data.items.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
          {(filter === 'active' || filter === 'all') && <MonthTimeline projects={projects.data.items} />}
        </>
      )}

      {creating && <NewProjectDialog defaultJobType={user.job_type} onClose={() => setCreating(false)} />}
    </>
  )
}
