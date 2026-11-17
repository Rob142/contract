import { describe, expect, it } from 'vitest'
import { dropIndex } from './kanbanDrop'

describe('kanban drop destinations', () => {
  it('accepts an empty column', () => expect(dropIndex([], undefined, false)).toBe(0))
  it('appends when dropped in the blank area of a nonempty column', () => {
    expect(dropIndex(['a', 'b'], undefined, false)).toBe(2)
  })
  it('inserts before or after the card under the pointer', () => {
    expect(dropIndex(['a', 'b'], 'b', false)).toBe(1)
    expect(dropIndex(['a', 'b'], 'b', true)).toBe(2)
    expect(dropIndex(['a', 'b'], 'a', false)).toBe(0)
  })
})
