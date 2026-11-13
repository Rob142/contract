import { useState, type FormEvent } from 'react'

import { messageOf } from '../api/messages'
import {
  useAddChecklistItem,
  useDeleteChecklistItem,
  useDeleteTask,
  useMoveTask,
  useToggleChecklistItem,
  useUpdateTask,
  type Task,
  type TaskStatus,
} from '../api/projects'
import { formatFullDate, localDateOf } from '../lib/format'
import { Dialog } from './Dialog'
import { SelectField, TextField } from './Field'

export const STATUS_LABELS: Record<TaskStatus, string> = { todo: '할 일', doing: '진행 중', done: '완료' }
const STATUS_OPTIONS = (Object.keys(STATUS_LABELS) as TaskStatus[]).map((value) => ({
  value,
  label: STATUS_LABELS[value],
}))

/** 작업 상세: 제목·라벨·마감일 수정, 상태 이동(터치 기기에서 칸반 이동 대신), 체크리스트, 삭제 */
export function TaskDialog({ task, onClose }: { task: Task; onClose: () => void }) {
  const projectId = task.project_id
  const update = useUpdateTask(projectId)
  const move = useMoveTask(projectId)
  const remove = useDeleteTask(projectId)
  const addItem = useAddChecklistItem(projectId, task.id)
  const toggleItem = useToggleChecklistItem(projectId, task.id)
  const deleteItem = useDeleteChecklistItem(projectId, task.id)

  const [title, setTitle] = useState(task.title)
  const [label, setLabel] = useState(task.label ?? '')
  const [dueDate, setDueDate] = useState(task.due_date ?? '')
  const [newItem, setNewItem] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)

  const dirty = title.trim() !== task.title || label.trim() !== (task.label ?? '') || dueDate !== (task.due_date ?? '')
  const error = update.error ?? move.error ?? remove.error ?? addItem.error ?? toggleItem.error ?? deleteItem.error

  const onSave = (e: FormEvent) => {
    e.preventDefault()
    if (!dirty || !title.trim()) return
    update.mutate(
      { id: task.id, title: title.trim(), label: label.trim() || null, due_date: dueDate || null, version: task.version },
      { onSuccess: onClose },
    )
  }

  const onAddItem = (e: FormEvent) => {
    e.preventDefault()
    const content = newItem.trim()
    if (!content) return
    addItem.mutate(content, { onSuccess: () => setNewItem('') })
  }

  const done = task.checklist.filter((i) => i.is_done).length

  const footer = (
    <>
      <button
        type="button"
        className="btn btn-danger-text"
        disabled={remove.isPending}
        onClick={() => (confirmDelete ? remove.mutate(task.id, { onSuccess: onClose }) : setConfirmDelete(true))}
      >
        {confirmDelete ? '정말 삭제할까요?' : '작업 삭제'}
      </button>
      <span className="spacer" />
      <button type="button" className="btn btn-secondary" onClick={onClose}>
        닫기
      </button>
      <button type="submit" form="task-form" className="btn btn-primary" disabled={!dirty || !title.trim() || update.isPending}>
        저장
      </button>
    </>
  )

  return (
    <Dialog open onClose={onClose} title="작업 상세" footer={footer}>
      <form id="task-form" className="form-grid" onSubmit={onSave} noValidate>
        <TextField
          label="작업명"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={200}
          error={title.trim() ? undefined : '작업명을 입력해 주세요.'}
          fieldClassName="span-2"
        />
        <TextField label="분류" placeholder="디자인, 납품 등" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={20} />
        <TextField label="마감일" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
        <SelectField
          label="상태"
          options={STATUS_OPTIONS}
          value={task.status}
          disabled={move.isPending}
          onChange={(e) => move.mutate({ taskId: task.id, status: e.target.value as TaskStatus, index: Number.MAX_SAFE_INTEGER })}
          hint={
            task.status === 'done' && task.completed_at
              ? `${formatFullDate(localDateOf(task.completed_at))}에 완료로 기록했어요.`
              : '바꾸면 해당 열의 맨 아래로 이동해요.'
          }
          fieldClassName="span-2"
        />
      </form>

      <section className="checklist" aria-labelledby="checklist-title">
        <h3 id="checklist-title">
          체크리스트 <span className="muted">{task.checklist.length > 0 && `${done} / ${task.checklist.length}`}</span>
        </h3>
        {task.checklist.length > 0 && (
          <ul>
            {task.checklist.map((item) => (
              <li key={item.id}>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={item.is_done}
                    onChange={(e) => toggleItem.mutate({ id: item.id, is_done: e.target.checked })}
                  />
                  <span className={item.is_done ? 'is-done' : undefined}>{item.content}</span>
                </label>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`${item.content} 삭제`}
                  onClick={() => deleteItem.mutate(item.id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
        <form className="inline-add" onSubmit={onAddItem}>
          <input
            className="input"
            placeholder="체크리스트 항목 추가"
            aria-label="체크리스트 항목"
            value={newItem}
            maxLength={200}
            onChange={(e) => setNewItem(e.target.value)}
          />
          <button type="submit" className="btn btn-secondary" disabled={!newItem.trim() || addItem.isPending}>
            추가
          </button>
        </form>
      </section>

      {error && (
        <div className="alert alert-error" role="alert" style={{ marginTop: 16 }}>
          {messageOf(error)}
        </div>
      )}
    </Dialog>
  )
}
