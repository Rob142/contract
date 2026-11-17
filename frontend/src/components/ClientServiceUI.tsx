import { useState, type FormEvent, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null
  const text =
    error instanceof ApiError
      ? error.status === 404
        ? '찾을 수 없거나 접근 권한이 없습니다.'
        : error.status === 422
          ? '입력 내용을 확인하세요. 필수 항목·금액·날짜·공개 동의를 확인해 주세요.'
          : error.message
      : error instanceof Error
        ? error.message
        : '요청을 처리하지 못했습니다. 다시 시도해 주세요.'
  return (
    <p className="alert alert-error" role="alert">
      {text}
    </p>
  )
}
export function ActionForm({
  title,
  children,
  onSubmit,
  label = '저장',
  className = '',
}: {
  title: string
  children: ReactNode
  onSubmit: (data: FormData) => Promise<unknown>
  label?: string
  className?: string
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [saved, setSaved] = useState(false)
  const qc = useQueryClient()
  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (pending) return
    const data = new FormData(e.currentTarget)
    setPending(true)
    setError(null)
    setSaved(false)
    try {
      await onSubmit(data)
      await qc.invalidateQueries({ queryKey: ['client-service'] })
      setSaved(true)
    } catch (err) {
      setError(err)
    } finally {
      setPending(false)
    }
  }
  return (
    <form
      className={`cs-form ${className}`}
      aria-label={title}
      onSubmit={(e) => void submit(e)}
    >
      <h3>{title}</h3>
      {children}
      <ErrorNotice error={error} />
      <div className="cs-actions">
        <button className="btn btn-primary" disabled={pending} type="submit">
          {pending ? '처리 중…' : label}
        </button>
        {saved && <span role="status">처리되었습니다.</span>}
      </div>
    </form>
  )
}
export function Input({
  label,
  name,
  value = '',
  type = 'text',
  required = false,
  hint = '',
  min,
  max,
}: {
  label: string
  name: string
  value?: string | number
  type?: string
  required?: boolean
  hint?: string
  min?: string
  max?: string
}) {
  return (
    <label className="cs-field">
      <span>
        {label}
        {required && ' *'}
      </span>
      <input
        name={name}
        type={type}
        defaultValue={value}
        required={required}
        min={min}
        max={max}
        maxLength={type === 'text' ? 300 : undefined}
        className="input"
      />
      {hint && <small>{hint}</small>}
    </label>
  )
}
export function Area({
  label,
  name,
  value = '',
  required = false,
}: {
  label: string
  name: string
  value?: string
  required?: boolean
}) {
  return (
    <label className="cs-field">
      <span>
        {label}
        {required && ' *'}
      </span>
      <textarea
        className="input"
        name={name}
        defaultValue={value}
        required={required}
        maxLength={5000}
        rows={3}
      />
    </label>
  )
}
export function Select({
  label,
  name,
  options,
  value,
}: {
  label: string
  name: string
  options: [string, string][]
  value?: string
}) {
  return (
    <label className="cs-field">
      <span>{label}</span>
      <select className="input" name={name} defaultValue={value}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </label>
  )
}
export function Check({
  label,
  name,
  checked = false,
  value,
}: {
  label: string
  name: string
  checked?: boolean
  value?: string
}) {
  return (
    <label className="checkbox">
      <input
        type="checkbox"
        name={name}
        value={value}
        defaultChecked={checked}
      />
      {label}
    </label>
  )
}
export const str = (data: FormData, key: string) =>
  String(data.get(key) ?? '').trim()
export const roles: [string, string][] = [
  ['owner', '소유자'],
  ['admin', '관리자'],
  ['member', '멤버'],
  ['viewer', '열람자'],
]
export const money = (value: string | null | undefined) =>
  value == null ? '견적 협의' : `${Number(value).toLocaleString('ko-KR')}원`
export const STATES: Record<string, string> = {
  draft: '작성 중',
  sent: '의뢰 전송',
  negotiating: '협의 중',
  quoted: '견적 제안',
  contracted: '계약 확정',
  pending: '검수 대기',
  approved: '승인',
  changes: '수정 요청',
  comment: '의견',
  seen: '확인',
  todo: '할 일',
  doing: '진행 중',
  done: '완료',
  active: '진행 중',
  completed: '완료',
  archived: '보관',
}
export function State({ value }: { value: string }) {
  return (
    <span className={`cs-state cs-state-${value}`}>
      {STATES[value] ?? value}
    </span>
  )
}
