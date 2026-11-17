import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from 'react'
import type { Task, TaskStatus } from '../api/projects'
import { dropIndex, type DropTarget } from './kanbanDrop'
import { groupTasksByDeadline } from './taskGroups'

type DragSession = {
  taskId: string
  pointerId: number
  x: number
  y: number
  active: boolean
  element: HTMLElement
}

export function useKanbanPointer(tasks: Task[], onMove: (taskId: string, target: DropTarget) => void) {
  const [dragId, setDragId] = useState<string | null>(null)
  const [target, setTarget] = useState<DropTarget | null>(null)
  const session = useRef<DragSession | null>(null)
  const latest = useRef({ tasks, onMove })
  const suppressClickUntil = useRef(0)

  useEffect(() => { latest.current = { tasks, onMove } }, [tasks, onMove])

  useEffect(() => {
    const destination = (x: number, y: number, taskId: string): DropTarget | null => {
      // Pointer capture changes event.target; hit-test the actual pointer location instead.
      const hit = document.elementFromPoint(x, y)
      const column = hit?.closest<HTMLElement>('[data-kanban-status]')
      const status = column?.dataset.kanbanStatus as TaskStatus | undefined
      if (!status || !['todo', 'doing', 'done'].includes(status)) return null
      const items = groupTasksByDeadline(latest.current.tasks.filter((t) => t.status === status)
        .sort((a, b) => a.position - b.position)).flatMap((group) => group.tasks)
      const card = hit?.closest<HTMLElement>('[data-task-id]')
      const ids = items.filter((task) => task.id !== taskId).map((task) => task.id)
      if (card?.dataset.taskId === taskId) {
        return { status, index: items.findIndex((task) => task.id === taskId) }
      }
      const rect = card?.getBoundingClientRect()
      return { status, index: dropIndex(ids, card?.dataset.taskId, Boolean(rect && y > rect.top + rect.height / 2)) }
    }
    const clear = () => {
      const active = session.current
      session.current = null
      if (active?.element.hasPointerCapture(active.pointerId)) active.element.releasePointerCapture(active.pointerId)
      setDragId(null)
      setTarget(null)
    }
    const move = (event: globalThis.PointerEvent) => {
      const active = session.current
      if (!active || event.pointerId !== active.pointerId) return
      if (!active.active) {
        if (Math.hypot(event.clientX - active.x, event.clientY - active.y) < 6) return
        active.active = true
        active.element.setPointerCapture(event.pointerId)
        setDragId(active.taskId)
      }
      event.preventDefault()
      const next = destination(event.clientX, event.clientY, active.taskId)
      setTarget((previous) => previous?.status === next?.status && previous?.index === next?.index ? previous : next)
    }
    const finish = (event: globalThis.PointerEvent) => {
      const active = session.current
      if (!active || event.pointerId !== active.pointerId) return
      const next = active.active ? destination(event.clientX, event.clientY, active.taskId) : null
      if (active.active) suppressClickUntil.current = performance.now() + 400
      clear()
      if (next) latest.current.onMove(active.taskId, next)
    }
    const cancel = (event: globalThis.PointerEvent) => {
      if (session.current?.pointerId === event.pointerId) clear()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && session.current) {
        suppressClickUntil.current = performance.now() + 400
        clear()
      }
    }
    document.addEventListener('pointermove', move, { passive: false })
    document.addEventListener('pointerup', finish)
    document.addEventListener('pointercancel', cancel)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointermove', move)
      document.removeEventListener('pointerup', finish)
      document.removeEventListener('pointercancel', cancel)
      document.removeEventListener('keydown', escape)
      const active = session.current
      if (active?.element.hasPointerCapture(active.pointerId)) active.element.releasePointerCapture(active.pointerId)
    }
  }, [])

  const onPointerDown = (event: PointerEvent<HTMLElement>, taskId: string) => {
    if (!event.isPrimary || event.button !== 0 || session.current) return
    const element = event.target as HTMLElement
    if (element.closest('input, select, textarea, a')) return
    // Keep touch scrolling on the card body; use its handle for touch drags.
    if (event.pointerType !== 'mouse' && !element.closest('.task-drag-handle')) return
    session.current = { taskId, pointerId: event.pointerId, x: event.clientX, y: event.clientY,
      active: false, element: event.currentTarget }
  }
  const onClickCapture = (event: MouseEvent<HTMLElement>) => {
    if (performance.now() < suppressClickUntil.current) {
      event.preventDefault()
      event.stopPropagation()
    }
  }
  return { dragId, target, onPointerDown, onClickCapture }
}
