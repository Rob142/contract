import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { api } from './client'
import { contractKeys } from './contracts'
import { keys as projectKeys, type ProjectDetail } from './projects'
import type { components } from './schema'

type S = components['schemas']
export type InvoiceSummary = S['InvoiceSummary']
export type InvoiceDetail = S['InvoiceDetail']
export type InvoiceList = S['InvoiceList']
export type InvoiceInput = S['InvoiceIn']
export type InvoiceItemInput = S['InvoiceItemIn']
export type InvoiceGroup = 'draft' | 'unpaid' | 'partial' | 'paid' | 'overdue' | 'cancelled' | 'outstanding'
export type BillingCandidates = S['BillingCandidates']
export type Payment = S['PaymentOut']
export type PaymentInput = S['PaymentIn']
export type ProjectDraft = S['ProjectDraft']
export type ProjectFromContract = S['ProjectFromContract']
export type PaymentTermInput = S['PaymentTermIn']

export const invoiceKeys = {
  all: ['invoices'] as const,
  list: (group: InvoiceGroup | 'all', month: string, projectId = '') => ['invoices', 'list', group, month, projectId] as const,
  detail: (id: string) => ['invoices', 'detail', id] as const,
  candidates: (projectId: string) => ['invoices', 'candidates', projectId] as const,
}

/** 청구·입금이 바뀌면 인보이스 목록, 프로젝트 미수액, 대시보드가 함께 바뀐다 */
function invalidateBilling(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: invoiceKeys.all })
  void qc.invalidateQueries({ queryKey: projectKeys.projects })
  void qc.invalidateQueries({ queryKey: projectKeys.dashboard })
}

export const invoicePdfUrl = (id: string, download = false) =>
  `/api/v1/invoices/${id}/pdf${download ? '?download=true' : ''}`
export const receiptPdfUrl = (paymentId: string, download = false) =>
  `/api/v1/payments/${paymentId}/receipt${download ? '?download=true' : ''}`

// ---------------------------------------------------------------- 조회
export function useInvoices(group: InvoiceGroup | 'all', month: string, projectId = '') {
  const params = new URLSearchParams({ limit: '100' })
  if (group !== 'all') params.set('group', group)
  if (month) params.set('month', month)
  if (projectId) params.set('project_id', projectId)
  return useQuery({
    queryKey: invoiceKeys.list(group, month, projectId),
    queryFn: () => api<InvoiceList>('GET', `/invoices?${params.toString()}`),
  })
}

export function useInvoice(id: string) {
  return useQuery({
    queryKey: invoiceKeys.detail(id),
    queryFn: () => api<InvoiceDetail>('GET', `/invoices/${id}`),
    enabled: Boolean(id),
  })
}

export function useBillingCandidates(projectId: string | null) {
  return useQuery({
    queryKey: invoiceKeys.candidates(projectId ?? ''),
    queryFn: () => api<BillingCandidates>('GET', `/projects/${projectId}/billing-candidates`),
    enabled: Boolean(projectId),
  })
}

// ---------------------------------------------------------------- 초안
export function useSaveInvoice(id?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: InvoiceInput & { version?: string }) =>
      id ? api<InvoiceDetail>('PUT', `/invoices/${id}`, body) : api<InvoiceDetail>('POST', '/invoices', body),
    onSuccess: (invoice) => {
      qc.setQueryData(invoiceKeys.detail(invoice.id), invoice)
      invalidateBilling(qc)
    },
  })
}

export function useDeleteInvoice(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('DELETE', `/invoices/${id}`),
    onSuccess: () => {
      qc.removeQueries({ queryKey: invoiceKeys.detail(id) })
      invalidateBilling(qc)
    },
  })
}

// ---------------------------------------------------------------- 발행·취소·재발행·입금 (재전송 키 사용)
function useInvoiceAction<TVars>(id: string, request: (vars: TVars) => Promise<InvoiceDetail>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: request,
    onSuccess: (invoice) => {
      qc.setQueryData(invoiceKeys.detail(invoice.id), invoice)
      if (invoice.id !== id) qc.setQueryData(invoiceKeys.detail(id), undefined)
      invalidateBilling(qc)
    },
  })
}

export function useIssueInvoice(id: string) {
  return useInvoiceAction(id, ({ dueDate, idempotencyKey }: { dueDate: string | null; idempotencyKey: string }) =>
    api<InvoiceDetail>('POST', `/invoices/${id}/issue`, { due_date: dueDate }, { headers: { 'Idempotency-Key': idempotencyKey } }),
  )
}

export function useCancelInvoice(id: string) {
  return useInvoiceAction(id, (reason: string) => api<InvoiceDetail>('POST', `/invoices/${id}/cancel`, { reason }))
}

export function useReissueInvoice(id: string) {
  return useInvoiceAction(id, () => api<InvoiceDetail>('POST', `/invoices/${id}/reissue`))
}

export function useRecordPayment(id: string) {
  return useInvoiceAction(id, ({ body, idempotencyKey }: { body: PaymentInput; idempotencyKey: string }) =>
    api<InvoiceDetail>('POST', `/invoices/${id}/payments`, body, { headers: { 'Idempotency-Key': idempotencyKey } }),
  )
}

export function useVoidPayment(invoiceId: string) {
  return useInvoiceAction(invoiceId, ({ paymentId, reason }: { paymentId: string; reason: string }) =>
    api<InvoiceDetail>('POST', `/payments/${paymentId}/void`, { reason }),
  )
}

// ---------------------------------------------------------------- 계약서 → 프로젝트 (07)
export function useProjectDraft(contractId: string) {
  return useQuery({
    queryKey: ['contracts', 'project-draft', contractId],
    queryFn: () => api<ProjectDraft>('POST', `/contracts/${contractId}/project-draft`),
    staleTime: 0,
    gcTime: 0,
  })
}

export function useCreateProjectFromContract(contractId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: ProjectFromContract; idempotencyKey: string }) =>
      api<ProjectDetail>('POST', `/contracts/${contractId}/project`, body, {
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
    onSuccess: (project) => {
      qc.setQueryData(projectKeys.project(project.id), project)
      void qc.invalidateQueries({ queryKey: projectKeys.projects })
      void qc.invalidateQueries({ queryKey: projectKeys.dashboard })
      void qc.invalidateQueries({ queryKey: projectKeys.clients })
      void qc.invalidateQueries({ queryKey: contractKeys.detail(contractId) })
    },
  })
}
