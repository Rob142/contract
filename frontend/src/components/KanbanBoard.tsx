import { useState, type CSSProperties, type PointerEvent, type FormEvent } from 'react'

import type { User } from '../api/auth'
import { messageOf } from '../api/messages'
import { useCreateTask, useMoveTask, type Task, type TaskStatus } from '../api/projects'
import { avatarInitial, daysBetween, formatShortDate, localDateOf } from '../lib/format'
import { groupTasksByDeadline } from '../lib/taskGroups'
import { useKanbanPointer } from '../lib/useKanbanPointer'
import type { DropTarget } from '../lib/kanbanDrop'
import { SelectField, TextField } from './Field'
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

function TaskCard({
  task,
  user,
  today,
  dragging,
  dropBefore,
  grouped,
  onOpen,
  onPointerDown,
}: {
  task: Task
  user: User
  today: string
  dragging: boolean
  dropBefore: boolean
  grouped: boolean
  onOpen: () => void
  onPointerDown: (e: PointerEvent<HTMLElement>) => void
}) {
  const checklistDone = task.checklist.filter((i) => i.is_done).length
  const overdue = task.status !== 'done' && task.due_date !== null && daysBetween(today, task.due_date) < 0

  return (
    <li
      className={['task-card', dragging && 'is-dragging', dropBefore && 'drop-before'].filter(Boolean).join(' ')}
      data-task-id={task.id}
      onPointerDown={onPointerDown}
      onDragStart={(e) => e.preventDefault()}
    >
      <button type="button" className="task-drag-handle"
        aria-label={`${task.title} 이동`} title="끌어서 다른 상태로 이동 · 클릭하면 상태 선택"
        onClick={onOpen}
      >⠿</button>
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
          <span className={overdue ? 'task-date is-overdue' : 'task-date'} hidden={grouped && task.status !== 'done'}>
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
  const [selectedStatus, setSelectedStatus] = useState<TaskStatus>(status)
  const [dueDate, setDueDate] = useState('')

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    const value = title.trim()
    if (!value) return onDone()
    create.mutate({ title: value, status: selectedStatus, due_date: dueDate || null }, { onSuccess: onDone })
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
      <SelectField label="추가할 상태" value={selectedStatus}
        options={COLUMNS.map((value) => ({ value, label: STATUS_LABELS[value] }))}
        onChange={(e) => setSelectedStatus(e.target.value as TaskStatus)} />
      <TextField label="마감일 (선택)" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)}
        hint="같은 열에서 마감일이 같은 작업은 함께 묶여요. 비워 두어도 돼요." />
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
  const [announcement, setAnnouncement] = useState('')
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
    groupTasksByDeadline(tasks.filter((t) => t.status === status).sort((a, b) => a.position - b.position)).flatMap((group) => group.tasks)
  const openTask = tasks.find((t) => t.id === openTaskId)

  const commitMove = (taskId: string, { status, index }: DropTarget) => {
    if (!taskId) return
    const current = tasks.find((t) => t.id === taskId)
    if (!current) return
    // 제자리에 놓은 경우는 요청하지 않는다
    const column = byColumn(status).filter((t) => t.id !== taskId)
    const clamped = Math.min(index, column.length)
    if (current.status === status && byColumn(status).indexOf(current) === clamped) return
    move.mutate({ taskId, status, index: clamped }, {
      onSuccess: () => setAnnouncement(`${current.title} 작업을 ${STATUS_LABELS[status]} 열로 이동했어요.`),
    })
  }

  const { dragId, target, onPointerDown, onClickCapture } = useKanbanPointer(tasks, commitMove)

  return (
    <>
      {move.isError && (
        <div className="alert alert-error" role="alert" style={{ marginBottom: 16 }}>
          {messageOf(move.error)} 화면을 서버 상태로 되돌렸어요.
        </div>
      )}
      <div role="status" aria-live="polite" className="kanban-announcement">{announcement}</div>
      <p className="field-hint">카드 본문이나 ⠿ 손잡이를 잡아 다른 열로 이동하세요. 터치 화면에서는 손잡이를 사용하세요. 클릭하면 상세가 열려요. 마감일은 선택 사항이에요.</p>
      <div className="kanban" style={columnsStyle} onClickCapture={onClickCapture}>
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
                data-kanban-status={status}
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
              data-kanban-status={status}
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
                {groupTasksByDeadline(items).map((group) => {
                  const cards = group.tasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    grouped={group.grouped}
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
                    onPointerDown={(e) => { if (!move.isPending) onPointerDown(e, task.id) }}
                  />
                  ))
                  return group.grouped ? (
                    <li key={group.key} className={`deadline-group deadline-tone-${Number(group.dueDate!.replaceAll('-', '')) % 3}`}>
                      <div className="deadline-group-title">{formatShortDate(group.dueDate!)} 마감 · {group.tasks.length}개</div>
                      <ul className="deadline-group-list">{cards}</ul>
                    </li>
                  ) : cards
                })}
                {items.length === 0 && <li className="kanban-empty">작업을 여기로 끌어 놓으세요.</li>}
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
