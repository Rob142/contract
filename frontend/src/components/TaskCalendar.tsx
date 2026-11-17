import { useId } from 'react'
import { Link } from 'react-router'
import { monthCells, shiftMonth } from '../lib/calendar'

export type CalendarEntry = {
  id: string
  title: string
  dueDate: string
  subtitle?: string
  status?: 'todo' | 'doing' | 'done'
  href?: string
}
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']
const STATUS = { todo: '할 일', doing: '진행 중', done: '완료' }

export function TaskCalendar({
  month,
  onMonthChange,
  today,
  entries,
  onOpen,
  loading = false,
  entryLabel = '작업',
}: {
  month: string
  onMonthChange: (month: string) => void
  today: string
  entries: CalendarEntry[]
  onOpen?: (id: string) => void
  entryLabel?: string
  loading?: boolean
}) {
  const id = useId()
  const cells = monthCells(month)
  const label = `${Number(month.slice(0, 4))}년 ${Number(month.slice(5))}월`
  const byDate = new Map<string, CalendarEntry[]>()
  for (const entry of entries) byDate.set(entry.dueDate, [...(byDate.get(entry.dueDate) ?? []), entry])
  const count = entries.filter((entry) => entry.dueDate.startsWith(month)).length
  return (
    <div className="task-calendar" aria-busy={loading}>
      <div className="calendar-toolbar">
        <h3 id={id} aria-live="polite">
          {label}
        </h3>
        <div className="calendar-navigation">
          <button
            type="button"
            className="btn btn-secondary"
            aria-label="이전 달"
            onClick={() => onMonthChange(shiftMonth(month, -1))}
          >
            ‹
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => onMonthChange(today.slice(0, 7))}>
            오늘
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            aria-label="다음 달"
            onClick={() => onMonthChange(shiftMonth(month, 1))}
          >
            ›
          </button>
        </div>
      </div>
      <p className="field-hint" role="status">
        {loading
          ? '일정을 불러오는 중이에요.'
          : `이 달의 ${entryLabel} ${count}개 · 항목을 누르면 상세를 확인할 수 있어요.`}
      </p>
      <div className="calendar-scroll" tabIndex={0} role="region" aria-label={`${label} 마감 일정 달력`}>
        <table className="calendar-table" aria-labelledby={id}>
          <caption className="calendar-caption">날짜별 {entryLabel}</caption>
          <thead>
            <tr>
              {WEEKDAYS.map((day) => (
                <th scope="col" key={day}>
                  {day}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 6 }, (_, week) => (
              <tr key={week}>
                {cells.slice(week * 7, week * 7 + 7).map((cell) => (
                  <td
                    key={cell.date}
                    className={[!cell.inMonth && 'calendar-outside', cell.date === today && 'calendar-today']
                      .filter(Boolean)
                      .join(' ')}
                  >
                    <time
                      dateTime={cell.date}
                      aria-current={cell.date === today ? 'date' : undefined}
                      className="calendar-date"
                    >
                      {cell.day}
                      {cell.date === today && <span> 오늘</span>}
                    </time>
                    {cell.inMonth && (
                      <ul className="calendar-events">
                        {(byDate.get(cell.date) ?? []).map((entry) => {
                          const overdue = entry.status !== 'done' && entry.dueDate < today
                          const text = (
                            <>
                              <span className="calendar-event-title">{entry.title}</span>
                              {entry.subtitle && <span className="calendar-event-subtitle">{entry.subtitle}</span>}
                              <span className="calendar-event-state">
                                {entry.status ? STATUS[entry.status] : '마감'}
                                {overdue && ' · 기한 지남'}
                              </span>
                            </>
                          )
                          const className = `calendar-event${entry.status === 'done' ? ' is-complete' : overdue ? ' is-overdue' : ''}`
                          const accessibleName = `${entry.title}${entry.subtitle ? ` · ${entry.subtitle}` : ''} · ${entry.dueDate}까지${entry.status ? ` · ${STATUS[entry.status]}` : ''}`
                          return (
                            <li key={entry.id}>
                              {entry.href ? (
                                <Link className={className} to={entry.href} aria-label={accessibleName}>
                                  {text}
                                </Link>
                              ) : (
                                <button
                                  type="button"
                                  className={className}
                                  aria-label={accessibleName}
                                  onClick={() => onOpen?.(entry.id)}
                                >
                                  {text}
                                </button>
                              )}
                            </li>
                          )
                        })}
                      </ul>
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
