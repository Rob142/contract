import { describe, expect, it } from 'vitest'
import { monthCells, shiftMonth } from './calendar'

describe('monthly calendar dates', () => {
  it('navigates across year boundaries', () => {
    expect(shiftMonth('2026-12', 1)).toBe('2027-01')
    expect(shiftMonth('2026-01', -1)).toBe('2025-12')
  })
  it('includes leap day and starts each week on Sunday', () => {
    const cells = monthCells('2028-02')
    expect(cells).toHaveLength(42)
    expect(cells.filter((cell) => cell.inMonth)).toHaveLength(29)
    expect(cells.some((cell) => cell.date === '2028-02-29' && cell.inMonth)).toBe(true)
    expect(new Date(`${cells[0]!.date}T00:00:00Z`).getUTCDay()).toBe(0)
  })
  it('does not lose dates in a month starting on Saturday', () => {
    const dates = monthCells('2026-08').filter((cell) => cell.inMonth)
    expect(dates[0]!.date).toBe('2026-08-01')
    expect(dates.at(-1)!.date).toBe('2026-08-31')
    expect(new Set(dates.map((cell) => cell.date)).size).toBe(31)
  })
})
