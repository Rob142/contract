import type { InvoiceSummary } from '../api/invoices'

/** 인보이스 상태 뱃지. 연체는 미수 잔액과 지급 기한으로 따로 판단한다 (설계서 6장) */
export function invoiceBadge(inv: Pick<InvoiceSummary, 'status' | 'payment_status' | 'is_overdue'>): {
  label: string
  className: string
} {
  if (inv.status === 'cancelled') return { label: '취소', className: 'badge badge-gray' }
  if (inv.status === 'draft') return { label: '초안', className: 'badge badge-gray' }
  if (inv.is_overdue) return { label: '연체', className: 'badge badge-red' }
  if (inv.payment_status === 'paid') return { label: '완납', className: 'badge badge-green' }
  if (inv.payment_status === 'partial') return { label: '일부 입금', className: 'badge badge-amber' }
  return { label: '미입금', className: 'badge badge-blue' }
}

export const PAYMENT_METHOD_LABELS: Record<string, string> = {
  bank_transfer: '계좌 입금',
  cash: '현금',
  card: '카드',
  other: '기타',
}
