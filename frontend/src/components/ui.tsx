import type { ReactNode } from 'react'

import { messageOf } from '../api/messages'

export function ProgressBar({ value, label }: { value: number | null; label: string }) {
  return (
    <div
      className="progress"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value ?? undefined}
      aria-valuetext={value === null ? '산정 전' : `${value}%`}
    >
      <span style={{ width: `${value ?? 0}%` }} />
    </div>
  )
}

export function Loading() {
  return (
    <div className="center-block" role="status">
      <div className="spinner" />
      <span className="visually-hidden">불러오는 중</span>
    </div>
  )
}

export function LoadError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="center-block">
      <p>{messageOf(error)}</p>
      <button type="button" className="btn btn-secondary" onClick={onRetry}>
        다시 시도
      </button>
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty-state">
      <p className="empty-title">{title}</p>
      {children}
    </div>
  )
}

export interface TabItem<T extends string> {
  value: T
  label: string
  count?: number
}

/** 밑줄형 필터 탭 */
export function FilterTabs<T extends string>({
  items,
  value,
  onChange,
  label,
}: {
  items: TabItem<T>[]
  value: T
  onChange: (value: T) => void
  label: string
}) {
  return (
    <div className="filter-tabs" role="tablist" aria-label={label}>
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          role="tab"
          aria-selected={item.value === value}
          className={item.value === value ? 'active' : undefined}
          onClick={() => onChange(item.value)}
        >
          {item.label}
          {item.count !== undefined && ` ${item.count}`}
        </button>
      ))}
    </div>
  )
}
