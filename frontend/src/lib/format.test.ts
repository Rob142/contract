import { describe, expect, it } from 'vitest'

import { ApiError, fieldErrorsOf } from '../api/client'
import { messageOf } from '../api/messages'
import { avatarInitial, displayName, safeNextPath, todayLine } from './format'

describe('displayName', () => {
  it('drops the family name of three-syllable Korean names', () => {
    expect(displayName('김지윤')).toBe('지윤')
    expect(avatarInitial('김지윤')).toBe('지')
  })

  it('keeps other names as they are', () => {
    expect(displayName('남궁민수')).toBe('남궁민수')
    expect(displayName(' Alex ')).toBe('Alex')
    expect(avatarInitial('')).toBe('?')
  })
})

describe('todayLine', () => {
  it('formats the dashboard date line', () => {
    expect(todayLine(new Date(2026, 10, 12))).toBe('오늘은 11월 12일 목요일이에요.')
  })
})

describe('safeNextPath', () => {
  it('allows only same-site paths', () => {
    expect(safeNextPath('/settings')).toBe('/settings')
    expect(safeNextPath('//evil.example')).toBe('/dashboard')
    expect(safeNextPath('https://evil.example')).toBe('/dashboard')
    expect(safeNextPath('/\\evil.example')).toBe('/dashboard')
    expect(safeNextPath(null)).toBe('/dashboard')
  })
})

describe('api errors', () => {
  it('maps validation details to fields', () => {
    const err = new ApiError(422, 'validation_error', 'x', [
      { loc: ['body', 'email'], msg: 'bad email' },
      { loc: ['body', 'password'], msg: 'too short' },
    ])
    expect(fieldErrorsOf(err)).toEqual({ email: 'bad email', password: 'too short' })
    expect(fieldErrorsOf(new Error('x'))).toEqual({})
  })

  it('translates known error codes', () => {
    expect(messageOf(new ApiError(401, 'invalid_credentials', 'x'))).toBe('이메일 또는 비밀번호가 올바르지 않아요.')
    expect(messageOf(new ApiError(500, 'internal_error', 'x'))).toContain('서버 오류')
  })
})

describe('money and dates', () => {
  it('groups digits without floating point', async () => {
    const { formatWon, groupDigits, digitsOnly } = await import('./format')
    expect(formatWon('1000000')).toBe('1,000,000원')
    expect(formatWon('0')).toBe('0원')
    expect(formatWon(null)).toBe('—')
    expect(groupDigits('99999999999999')).toBe('99,999,999,999,999')
    expect(groupDigits('2.50')).toBe('2.50')
    expect(digitsOnly('1,000,000원')).toBe('1000000')
    expect(digitsOnly('007')).toBe('7')
  })

  it('formats plain dates without timezone shifts', async () => {
    const { formatMonthDay, formatShortDate, formatFullDate, daysBetween } = await import('./format')
    expect(formatMonthDay('2026-11-05')).toBe('11월 05일')
    expect(formatShortDate('2026-11-14')).toBe('11.14')
    expect(formatFullDate('2026-01-02')).toBe('2026.01.02')
    expect(daysBetween('2026-11-12', '2026-11-14')).toBe(2)
    expect(daysBetween('2026-12-31', '2027-01-01')).toBe(1)
  })
})

describe('applyMove', () => {
  it('matches the server reorder rule', async () => {
    const { applyMove } = await import('../api/projects')
    const t = (id: string, status: 'todo' | 'doing' | 'done', position: number) =>
      ({ id, status, position }) as Parameters<typeof applyMove>[0][number]
    const tasks = [t('a', 'todo', 0), t('b', 'todo', 1), t('c', 'todo', 2), t('d', 'done', 0)]

    const moved = applyMove(tasks, 'c', 'todo', 0)
    const todo = moved.filter((x) => x.status === 'todo').sort((x, y) => x.position - y.position)
    expect(todo.map((x) => x.id)).toEqual(['c', 'a', 'b'])

    const toDone = applyMove(tasks, 'a', 'done', 99)
    const done = toDone.filter((x) => x.status === 'done').sort((x, y) => x.position - y.position)
    expect(done.map((x) => x.id)).toEqual(['d', 'a'])
  })
})
