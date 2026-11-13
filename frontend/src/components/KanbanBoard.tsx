import { useState, type CSSProperties, type DragEvent, type FormEvent } from 'react'

import type { User } from '../api/auth'
import { messageOf } from '../api/messages'
import { useCreateTask, useMoveTask, type Task, type TaskStatus } from '../api/projects'
import { avatarInitial, daysBetween, formatShortDate, localDateOf } from '../lib/format'
import { STATUS_LABELS, TaskDialog } from './TaskDialog'

const COLUMNS: TaskStatus[] = ['todo', 'doing', 'done']
const COLLAPSE_KEY = 'fh.kanban.collapsed'

/** 접은 열은 이 브라우저에만 기억한다 (저장소를 못 쓰면 매번 펼친 상태로 시작) */
function loadCollapsed(): TaskStatus[] {
  try {
    const raw = JSON.parse(localStorage.getItem(COLLAPSE_KEY) ?? '[]') as unknown
    return Array.isArray(raw) ? COLUMNS.filter((c) => raw.includes(c)) : []
  } catch {
    return []
  }
}

function saveCollapsed(value: TaskStatus[]) {
  try {
    localStorage.setItem(COLLAPSE_KEY, JSON.stringify(value))
  } catch {
    // 저장하지 못해도 화면 동작에는 영향 없음
  }
}

type DropTarget = { status: TaskStatus; index: number }

function TaskCard({
  task,
  user,
  today,
  dragging,
  dropBefore,
  onOpen,
  onDragStart,
  onDragEnd,
  onDragOverCard,
}: {
  task: Task
  user: User
  today: string
  dragging: boolean
  dropBefore: boolean
  onOpen: () => void
  onDragStart: () => void
  onDragEnd: () => void
  onDragOverCard: (e: DragEvent<HTMLElement>) => void
}) {
  const checklistDone = task.checklist.filter((i) => i.is_done).length
  const overdue = task.status !== 'done' && task.due_date !== null && daysBetween(today, task.due_date) < 0

  return (
    <li
      className={['task-card', dragging && 'is-dragging', dropBefore && 'drop-before'].filter(Boolean).join(' ')}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'move'
        e.dataTransfer.setData('text/plain', task.id)
        onDragStart()
      }}
      onDragEnd={onDragEnd}
      onDragOver={onDragOverCard}
    >
      <button type="button" className="task-card-button" onClick={onOpen}>
        {task.label && <span className="badge badge-gray">{task.label}</span>}
        <strong className="task-title">{task.title}</strong>
        {task.status === 'done' ? (
          <span className="task-meta task-meta-done">✓ 완료 기록 저장됨</span>
        ) : task.checklist.length > 0 ? (
          <span className="task-meta">
            체크리스트 {checklistDone} / {task.checklist.length}
          </span>
        ) : null}
        <span className="task-foot">
          <span className={overdue ? 'task-date is-overdue' : 'task-date'}>
            {task.status === 'done' && task.completed_at
              ? `완료 ${formatShortDate(localDateOf(task.completed_at))}`
              : task.due_date
                ? `마감 ${formatShortDate(task.due_date)}${overdue ? ' · 지남' : ''}`
                : '마감일 없음'}
          </span>
          <span className="avatar avatar-sm" aria-hidden="true">
            {avatarInitial(user.name)}
          </span>
        </span>
      </button>
    </li>
  )
}

function AddTaskForm({ projectId, status, onDone }: { projectId: string; status: TaskStatus; onDone: () => void }) {
  const create = useCreateTask(projectId)
  const [title, setTitle] = useState('')

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const value = title.trim()
    if (!value) return onDone()
    create.mutate({ title: value, status }, { onSuccess: () => setTitle('') })
  }

  return (
    <form className="add-task-form" onSubmit={onSubmit}>
      <input
        className="input"
        placeholder="작업명을 입력하고 Enter"
        aria-label={`${STATUS_LABELS[status]}에 작업 추가`}
        value={title}
        maxLength={200}
        autoFocus
        onChange={(e) => setTitle(e.target.value)}
        onKeyDown={(e) => e.key === 'Escape' && onDone()}
      />
      <div className="add-task-actions">
        <button type="submit" className="btn btn-primary" disabled={create.isPending}>
          추가
        </button>
        <button type="button" className="btn btn-secondary" onClick={onDone}>
          취소
        </button>
      </div>
      {create.isError && <span className="field-error">{messageOf(create.error)}</span>}
    </form>
  )
}

/** 09 칸반. 데스크톱은 끌어다 놓기, 터치 기기는 카드를 눌러 상태를 바꾼다. */
export function KanbanBoard({
  projectId,
  tasks,
  user,
  today,
  addingTo,
  setAddingTo,
}: {
  projectId: string
  tasks: Task[]
  user: User
  today: string
  addingTo: TaskStatus | null
  setAddingTo: (status: TaskStatus | null) => void
}) {
  const move = useMoveTask(projectId)
  const [dragId, setDragId] = useState<string | null>(null)
  const [target, setTarget] = useState<DropTarget | null>(null)
  const [openTaskId, setOpenTaskId] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<TaskStatus[]>(loadCollapsed)
  const toggleColumn = (status: TaskStatus) =>
    setCollapsed((cur) => {
      const next = cur.includes(status) ? cur.filter((c) => c !== status) : [...cur, status]
      saveCollapsed(next)
      return next
    })
  const columnsStyle = {
    '--kanban-cols': COLUMNS.map((c) => (collapsed.includes(c) ? '76px' : 'minmax(0, 1fr)')).join(' '),
    '--kanban-cols-mobile': COLUMNS.map((c) => (collapsed.includes(c) ? '76px' : '86%')).join(' '),
  } as CSSProperties

  const byColumn = (status: TaskStatus) =>
    tasks.filter((t) => t.status === status).sort((a, b) => a.position - b.position)
  const openTask = tasks.find((t) => t.id === openTaskId)

  const resetDrag = () => {
    setDragId(null)
    setTarget(null)
  }

  const onDrop = (e: DragEvent<HTMLElement>, status: TaskStatus) => {
    e.preventDefault()
    const taskId = dragId ?? e.dataTransfer.getData('text/plain')
    const index = target?.status === status ? target.index : Number.MAX_SAFE_INTEGER
    resetDrag()
    if (!taskId) return
    const current = tasks.find((t) => t.id === taskId)
    if (!current) return
    // 제자리에 놓은 경우는 요청하지 않는다
    const column = byColumn(status).filter((t) => t.id !== taskId)
    const clamped = Math.min(index, column.length)
    if (current.status === status && byColumn(status).indexOf(current) === clamped) return
    move.mutate({ taskId, status, index: clamped })
  }

  return (
    <>
      {move.isError && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 16 }}>
          {messageOf(move.error)} 화면을 서버 상태로 되돌렸어요.
        </div>
      )}
      <div className="kanban" style={columnsStyle}>
        {COLUMNS.map((status) => {
          const items = byColumn(status)
          // 드롭 위치 계산은 끌고 있는 카드를 뺀 목록 기준 (서버 규칙과 같다)
          const others = items.filter((t) => t.id !== dragId)
          const isCollapsed = collapsed.includes(status)
          if (isCollapsed) {
            // 접힌 열: 이름과 개수만. 눌러서 펼치고, 카드를 끌어다 놓을 수도 있다
            return (
              <section
                key={status}
                className={target?.status === status ? 'kanban-column is-collapsed is-over' : 'kanban-column is-collapsed'}
                aria-labelledby={`col-${status}`}
                onDragOver={(e) => {
                  e.preventDefault()
                  if (target?.status !== status) setTarget({ status, index: others.length })
                }}
                onDrop={(e) => onDrop(e, status)}
              >
                <button
                  type="button"
                  className="kanban-expand"
                  aria-expanded="false"
                  aria-label={`${STATUS_LABELS[status]} 열 펼치기 (${items.length}개)`}
                  onClick={() => toggleColumn(status)}
                >
                  <span aria-hidden="true">›</span>
                  <h2 id={`col-${status}`}>{STATUS_LABELS[status]}</h2>
                  <span className="kanban-count">{items.length}</span>
                </button>
              </section>
            )
          }
          return (
            <section
              key={status}
              className={target?.status === status ? 'kanban-column is-over' : 'kanban-column'}
              aria-labelledby={`col-${status}`}
              onDragOver={(e) => {
                e.preventDefault()
                if (target?.status !== status) setTarget({ status, index: others.length })
              }}
              onDrop={(e) => onDrop(e, status)}
            >
              <header className="kanban-head">
                <h2 id={`col-${status}`}>
                  {STATUS_LABELS[status]} <span className="muted">{items.length}</span>
                </h2>
                <span className="kanban-head-actions">
                  <button
                    type="button"
                    className="icon-button"
                    aria-label={`${STATUS_LABELS[status]}에 작업 추가`}
                    onClick={() => setAddingTo(status)}
                  >
                    +
                  </button>
                  <button
                    type="button"
                    className="icon-button"
                    aria-expanded="true"
                    aria-label={`${STATUS_LABELS[status]} 열 접기`}
                    title="열 접기"
                    onClick={() => toggleColumn(status)}
                  >
                    ‹
                  </button>
                </span>
              </header>

              <ul className="kanban-list">
                {items.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    user={user}
                    today={today}
                    dragging={task.id === dragId}
                    dropBefore={
                      dragId !== null &&
                      task.id !== dragId &&
                      target?.status === status &&
                      others[target.index]?.id === task.id
                    }
                    onOpen={() => setOpenTaskId(task.id)}
                    onDragStart={() => setDragId(task.id)}
                    onDragEnd={resetDrag}
                    onDragOverCard={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      if (task.id === dragId) return
                      const rect = e.currentTarget.getBoundingClientRect()
                      const after = e.clientY > rect.top + rect.height / 2
                      const index = others.findIndex((t) => t.id === task.id) + (after ? 1 : 0)
                      if (target?.status !== status || target.index !== index) setTarget({ status, index })
                    }}
                  />
                ))}
                {dragId !== null && target?.status === status && target.index >= others.length && (
                  <li className="drop-end" aria-hidden="true" />
                )}
              </ul>

              {addingTo === status ? (
                <AddTaskForm projectId={projectId} status={status} onDone={() => setAddingTo(null)} />
              ) : (
                <button type="button" className="add-task-button" onClick={() => setAddingTo(status)}>
                  + 작업 추가
                </button>
              )}
            </section>
          )
        })}
      </div>

      {openTask && <TaskDialog key={openTask.id} task={openTask} onClose={() => setOpenTaskId(null)} />}
    </>
  )
}
