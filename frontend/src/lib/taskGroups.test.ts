import { describe, expect, it } from 'vitest'
import { groupTasksByDeadline } from './taskGroups'

const task = (id: string, due_date: string | null) => ({ id, due_date })

describe('groupTasksByDeadline', () => {
  it('groups nonadjacent tasks with the same date and keeps each task once', () => {
    const groups = groupTasksByDeadline([task('a', '2026-12-01'), task('b', '2026-12-02'), task('c', '2026-12-01')])
    expect(groups.map((g) => [g.grouped, g.tasks.map((t) => t.id)])).toEqual([[true, ['a', 'c']], [false, ['b']]])
  })
  it('keeps undated tasks and unique dates as individual cards', () => {
    const groups = groupTasksByDeadline([task('a', null), task('b', null), task('c', '2026-12-02')])
    expect(groups).toHaveLength(3)
    expect(groups.every((g) => !g.grouped)).toBe(true)
  })
  it('splits a group when a task is moved out or its date changes', () => {
    expect(groupTasksByDeadline([task('a', '2026-12-01')])[0]!.grouped).toBe(false)
    expect(groupTasksByDeadline([task('a', '2026-12-01'), task('c', '2026-12-03')]).every((g) => !g.grouped)).toBe(true)
  })
})
