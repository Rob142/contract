import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useMe } from '../api/auth'
import type { components } from '../api/schema'
import { useCalendarTasks } from '../api/projects'
import { ActionForm, Area, Check, ErrorNotice, Input, str } from './ClientServiceUI'
import { Dialog } from './Dialog'
import { TaskCalendar, type CalendarEntry } from './TaskCalendar'

type Event = components['schemas']['EventOut']

/** Personal entries never acquire a project_id or a client-visible flag. */
export function PersonalCalendar({ today, projectEntries }: { today: string; projectEntries?: CalendarEntry[] }) {
  const [month, setMonth] = useState(today.slice(0, 7))
  const [overlay, setOverlay] = useState(false)
  const [editing, setEditing] = useState<Event | 'new' | null>(null)
  const qc = useQueryClient()
  const me = useMe()
  const personal = useQuery({
    queryKey: ['personal-calendar', me.data?.id, month],
    enabled: !!me.data,
    queryFn: () => api<Event[]>('GET', `/personal-calendar?month=${month}`),
  })
  const deadlines = useCalendarTasks(month, projectEntries === undefined && overlay)
  const shared =
    projectEntries ??
    (deadlines.data ?? []).map((t) => ({
      id: t.task_id,
      title: t.title,
      dueDate: t.due_date,
      subtitle: t.project_name,
      href: `/projects/${t.project_id}?tab=schedule&task=${t.task_id}`,
    }))
  const event = editing && editing !== 'new' ? editing : null
  const refresh = () => qc.invalidateQueries({ queryKey: ['personal-calendar'] })
  return (
    <>
      <p className="cs-note">
        나만 보는 개인 일정입니다. 제목·메모·완료 여부는 클라이언트나 팀원에게 공유되지 않습니다. 클라이언트와 함께
        관리할 일정은 프로젝트의 일정 탭에 등록하세요.
      </p>
      <div className="cs-actions">
        <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>
          개인 일정 추가
        </button>
        <label className="checkbox">
          <input type="checkbox" checked={overlay} onChange={(e) => setOverlay(e.target.checked)} />
          프로젝트 공유 일정도 함께 보기
        </label>
      </div>
      <ErrorNotice error={personal.error} />
      {overlay && <ErrorNotice error={deadlines.error} />}
      <TaskCalendar
        month={month}
        onMonthChange={setMonth}
        today={today}
        loading={personal.isPending || (overlay && projectEntries === undefined && deadlines.isPending)}
        entryLabel="일정"
        entries={[
          ...(personal.data ?? []).map((e) => ({
            id: e.id,
            title: e.title,
            dueDate: e.scheduled_on,
            status: e.is_done ? ('done' as const) : ('todo' as const),
            subtitle: '나만 보기 · 개인 일정',
          })),
          ...(overlay ? shared.map((e) => ({ ...e, subtitle: `프로젝트 공유 · ${e.subtitle ?? ''}` })) : []),
        ]}
        onOpen={(id) => {
          const found = personal.data?.find((e) => e.id === id)
          if (found) setEditing(found)
        }}
      />
      {!personal.isPending && !personal.error && !personal.data?.length && (
        <p className="field-hint">이 달에 등록한 개인 일정이 없습니다. 개인 일정 추가로 시작하세요.</p>
      )}
      {editing && (
        <Dialog open title={event ? '개인 일정 수정' : '개인 일정 추가'} onClose={() => setEditing(null)}>
          <ActionForm
            title="나만 보는 일정"
            label="개인 일정 저장"
            onSubmit={async (d) => {
              const body = {
                title: str(d, 'title'),
                notes: str(d, 'notes'),
                scheduled_on: str(d, 'scheduled_on'),
                is_done: d.has('is_done'),
              }
              await api(
                event ? 'PUT' : 'POST',
                event ? `/personal-calendar/${event.id}` : '/personal-calendar',
                event ? { ...body, version: event.updated_at } : body,
              )
              await refresh()
              setMonth(body.scheduled_on.slice(0, 7))
              setEditing(null)
            }}
          >
            <Input label="일정 제목" name="title" value={event?.title} required />
            <Input
              label="날짜"
              name="scheduled_on"
              type="date"
              value={event?.scheduled_on ?? (today.startsWith(month) ? today : `${month}-01`)}
              required
            />
            <Area label="나만 보는 메모" name="notes" value={event?.notes} />
            <Check label="완료한 일정" name="is_done" checked={event?.is_done} />
            <p className="field-hint">개인 일정을 저장해도 프로젝트 일정에는 추가되지 않습니다.</p>
          </ActionForm>
          {event && (
            <ActionForm
              title="개인 일정 보관"
              label="일정 보관하기"
              onSubmit={async () => {
                await api('DELETE', `/personal-calendar/${event.id}`)
                await refresh()
                setEditing(null)
              }}
            >
              <p className="field-hint">캘린더에서 숨깁니다. 원본 기록은 보존됩니다.</p>
            </ActionForm>
          )}
        </Dialog>
      )}
    </>
  )
}
