import type { JobType, LlmMode } from '../api/auth'

export const JOB_TYPE_LABELS: Record<JobType, string> = {
  design: '디자이너',
  dev: '개발자',
  video: '영상 제작자',
  marketing: '마케터',
  writing: '작가·콘텐츠 작성자',
  translation: '번역가·통역사',
  education: '강사·교육 전문가',
  consulting: '컨설턴트·기획자',
  photography: '사진가',
  other: '기타 프리랜서',
}

export const LLM_MODE_LABELS: Record<LlmMode, string> = {
  ask: '매번 선택',
  commercial: '상용 LLM API',
  local: '로컬 LLM',
}

/** 인사말용 이름: 세 글자 한글 이름은 성을 뺀다 (김지윤 → 지윤). */
export function displayName(name: string): string {
  const trimmed = name.trim()
  return /^[가-힣]{3}$/.test(trimmed) ? trimmed.slice(1) : trimmed
}

export function avatarInitial(name: string): string {
  return displayName(name).charAt(0) || '?'
}

/** 오늘은 11월 12일 목요일이에요. */
export function todayLine(date: Date = new Date()): string {
  const weekday = new Intl.DateTimeFormat('ko-KR', { weekday: 'long' }).format(date)
  return `오늘은 ${date.getMonth() + 1}월 ${date.getDate()}일 ${weekday}이에요.`
}

/** 로그인 후 돌아갈 경로. 외부 주소로 보내는 열린 리다이렉트를 막는다. */
export function safeNextPath(next: string | null, fallback = '/dashboard'): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return fallback
  return next
}

/** 칸반·카드용 짧은 직업군 이름 */
export const JOB_TYPE_SHORT: Record<JobType, string> = {
  design: '디자인',
  dev: '개발',
  video: '영상',
  marketing: '마케팅',
  writing: '글·콘텐츠',
  translation: '번역·통역',
  education: '교육',
  consulting: '컨설팅·기획',
  photography: '사진',
  other: '기타',
}

// ---------------------------------------------------------------- 금액 (십진 문자열 그대로, 부동소수점 금지)

/** "1000000" → "1,000,000" */
export function groupDigits(value: string | number): string {
  const text = String(value)
  const negative = text.startsWith('-')
  const digits = negative ? text.slice(1) : text
  const [whole = '0', fraction] = digits.split('.')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${negative ? '-' : ''}${grouped}${fraction ? `.${fraction}` : ''}`
}

/** "1000000" → "1,000,000원" */
export function formatWon(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === '' ? '—' : `${groupDigits(value)}원`
}

/** 입력란의 금액 문자열에서 숫자만 남긴다 ("1,000,000원" → "1000000") */
export function digitsOnly(input: string): string {
  return input.replace(/\D/g, '').replace(/^0+(?=\d)/, '')
}

// ---------------------------------------------------------------- 날짜 (YYYY-MM-DD 문자열을 시간대 변환 없이 다룬다)

function parts(isoDate: string): [number, number, number] {
  const [y = 0, m = 0, d = 0] = isoDate.slice(0, 10).split('-').map(Number)
  return [y, m, d]
}

/** "2026-11-20" → "11월 20일" */
export function formatMonthDay(isoDate: string): string {
  const [, m, d] = parts(isoDate)
  return `${m}월 ${String(d).padStart(2, '0')}일`
}

/** "2026-11-14" → "11.14" */
export function formatShortDate(isoDate: string): string {
  const [, m, d] = parts(isoDate)
  return `${m}.${String(d).padStart(2, '0')}`
}

/** "2026-11-12" → "2026.11.12" */
export function formatFullDate(isoDate: string): string {
  const [y, m, d] = parts(isoDate)
  return `${y}.${String(m).padStart(2, '0')}.${String(d).padStart(2, '0')}`
}

/** 서버 시각(ISO 타임스탬프)을 사용자 시간대의 YYYY-MM-DD로 */
export function localDateOf(timestamp: string): string {
  const date = new Date(timestamp)
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** 두 날짜 사이의 일수 (b - a) */
export function daysBetween(a: string, b: string): number {
  const [ay, am, ad] = parts(a)
  const [by, bm, bd] = parts(b)
  return Math.round((Date.UTC(by, bm - 1, bd) - Date.UTC(ay, am - 1, ad)) / 86_400_000)
}

/** 사용자 기기 기준 오늘 (YYYY-MM-DD) */
export function todayIso(): string {
  return localDateOf(new Date().toISOString())
}
