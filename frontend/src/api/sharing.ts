import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef } from 'react'

import { api, ApiError } from './client'
import type { components } from './schema'

type S = components['schemas']
export type ShareLink = S['ShareLinkOut']
export type ShareLinkUpdate = S['ShareLinkUpdate']
export type Feedback = S['FeedbackOut']
export type ViewEvent = S['ViewEventOut']
export type RevisionState = S['RevisionState']
export type RevisionRequest = S['RevisionRequestOut']
export type Attachment = S['AttachmentOut']
export type AttachmentKind = Attachment['kind']
export type PublicProject = S['PublicProject']
export type PublicTask = S['PublicTask']
export type MonthlyIncome = S['MonthlyIncomeOut']
export type MonthDetail = S['MonthDetail']
export type EvidenceDoc = S['EvidenceDoc']
export type Portfolio = S['PortfolioOut']
export type PortfolioDraft = S['PortfolioDraft']
export type PublicPortfolio = S['PublicPortfolio']
export type JobTemplate = S['JobTemplateOut']

export const sharingKeys = {
  link: (projectId: string) => ['sharing', 'link', projectId] as const,
  events: (projectId: string) => ['sharing', 'events', projectId] as const,
  feedback: (projectId: string) => ['sharing', 'feedback', projectId] as const,
  revisions: (projectId: string) => ['sharing', 'revisions', projectId] as const,
  attachments: (projectId: string) => ['sharing', 'attachments', projectId] as const,
  public: (token: string) => ['public', token] as const,
  income: ['settlement', 'income'] as const,
  monthDetail: (month: string) => ['settlement', 'month', month] as const,
  evidence: ['settlement', 'evidence'] as const,
  portfolio: ['portfolio'] as const,
}

/** multipart 업로드. Content-Type은 브라우저가 경계 문자열과 함께 채운다. */
async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api/v1${path}`, { method: 'POST', credentials: 'same-origin', body: form })
  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const error = (data as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error
    throw new ApiError(res.status, error?.code ?? 'http_error', error?.message ?? res.statusText, error?.details)
  }
  return data as T
}

// ---------------------------------------------------------------- 공유 링크
export function useShareLink(projectId: string) {
  return useQuery({
    queryKey: sharingKeys.link(projectId),
    queryFn: () => api<{ link: ShareLink | null }>('GET', `/projects/${projectId}/share-link`),
  })
}

export function useShareLinkActions(projectId: string) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: sharingKeys.link(projectId) })
  return {
    create: useMutation({
      mutationFn: () => api<ShareLink>('POST', `/projects/${projectId}/share-link`),
      onSuccess: refresh,
    }),
    regenerate: useMutation({
      mutationFn: () => api<ShareLink>('POST', `/projects/${projectId}/share-link/regenerate`),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: (body: ShareLinkUpdate) => api<ShareLink>('PATCH', `/projects/${projectId}/share-link`, body),
      onSuccess: refresh,
    }),
    revoke: useMutation({
      mutationFn: () => api<void>('DELETE', `/projects/${projectId}/share-link`),
      onSuccess: refresh,
    }),
  }
}

export function useViewEvents(projectId: string) {
  return useQuery({
    queryKey: sharingKeys.events(projectId),
    queryFn: () => api<ViewEvent[]>('GET', `/projects/${projectId}/view-events`),
  })
}

export function useProjectFeedback(projectId: string) {
  return useQuery({
    queryKey: sharingKeys.feedback(projectId),
    queryFn: () => api<Feedback[]>('GET', `/projects/${projectId}/feedback`),
  })
}

export function useAddFeedback(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ taskId, body }: { taskId: string; body: string }) =>
      api<Feedback>('POST', `/tasks/${taskId}/feedback`, { body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: sharingKeys.feedback(projectId) }),
  })
}

// ---------------------------------------------------------------- 수정 카운터
export function useRevisions(projectId: string) {
  return useQuery({
    queryKey: sharingKeys.revisions(projectId),
    queryFn: () => api<RevisionState>('GET', `/projects/${projectId}/revisions`),
  })
}

export function useRevisionActions(projectId: string) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: sharingKeys.revisions(projectId) })
  return {
    exclude: useMutation({
      mutationFn: ({ id, reason }: { id: string; reason: string }) =>
        api<RevisionState>('POST', `/revision-requests/${id}/exclude`, { reason }),
      onSuccess: refresh,
    }),
    quote: useMutation({
      mutationFn: (body: { title: string; amount: string; revision_request_id?: string }) =>
        api('POST', `/projects/${projectId}/extra-quotes`, body),
      onSuccess: refresh,
    }),
  }
}

// ---------------------------------------------------------------- 첨부
export function useAttachments(projectId: string, kind?: AttachmentKind) {
  return useQuery({
    queryKey: [...sharingKeys.attachments(projectId), kind ?? 'all'],
    queryFn: () => api<Attachment[]>('GET', `/projects/${projectId}/attachments${kind ? `?kind=${kind}` : ''}`),
  })
}

export function useAttachmentActions(projectId: string) {
  const qc = useQueryClient()
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: sharingKeys.attachments(projectId) })
    void qc.invalidateQueries({ queryKey: sharingKeys.evidence })
  }
  return {
    addLink: useMutation({
      mutationFn: (body: { title: string; url: string; kind?: AttachmentKind; task_id?: string | null }) =>
        api<Attachment>('POST', `/projects/${projectId}/attachments/link`, body),
      onSuccess: refresh,
    }),
    addFile: useMutation({
      mutationFn: (form: FormData) => upload<Attachment>(`/projects/${projectId}/attachments/file`, form),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api<void>('DELETE', `/attachments/${id}`),
      onSuccess: refresh,
    }),
  }
}

// ---------------------------------------------------------------- 클라이언트 공개 페이지 (로그인 없음)
export function usePublicProject(token: string) {
  // 처음 불러올 때만 "열람" 기록을 남기고, 이후 새로고침(피드백 반영 등)은 기록하지 않는다
  const first = useRef(true)
  return useQuery({
    queryKey: sharingKeys.public(token),
    queryFn: () => {
      const record = first.current
      first.current = false
      return api<PublicProject>('GET', `/public/p/${token}?record=${record}`)
    },
    retry: false,
    refetchOnWindowFocus: false,
  })
}

export function usePublicActions(token: string) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: sharingKeys.public(token) })
  return {
    ack: useMutation({
      mutationFn: ({ taskId, viewer }: { taskId: string; viewer?: string }) =>
        api<void>('POST', `/public/p/${token}/tasks/${taskId}/ack`, { viewer_name: viewer || null }),
      onSuccess: refresh,
    }),
    feedback: useMutation({
      mutationFn: ({ taskId, body, name }: { taskId: string; body: string; name?: string }) =>
        api<Feedback>('POST', `/public/p/${token}/tasks/${taskId}/feedback`, { body, author_name: name || null }),
      onSuccess: refresh,
    }),
    revision: useMutation({
      mutationFn: ({ body, name, taskId }: { body: string; name?: string; taskId?: string }) =>
        api<RevisionRequest>('POST', `/public/p/${token}/revision-requests`, {
          body,
          requester_name: name || null,
          task_id: taskId || null,
        }),
      onSuccess: refresh,
    }),
  }
}

// ---------------------------------------------------------------- 정산
export function useMonthlyIncome(months = 12) {
  return useQuery({
    queryKey: [...sharingKeys.income, months],
    queryFn: () => api<MonthlyIncome>('GET', `/settlement/monthly-income?months=${months}`),
  })
}

export function useMonthDetail(month: string | null) {
  return useQuery({
    queryKey: sharingKeys.monthDetail(month ?? ''),
    queryFn: () => api<MonthDetail>('GET', `/settlement/monthly-income/${month}`),
    enabled: month !== null,
  })
}

export function useEvidence() {
  return useQuery({ queryKey: sharingKeys.evidence, queryFn: () => api<EvidenceDoc[]>('GET', '/settlement/evidence') })
}

// ---------------------------------------------------------------- 포트폴리오
export function usePortfolio() {
  return useQuery({
    queryKey: sharingKeys.portfolio,
    queryFn: () => api<{ items: Portfolio[] }>('GET', '/portfolio'),
  })
}

export function usePortfolioDraft() {
  return useMutation({ mutationFn: (projectId: string) => api<PortfolioDraft>('POST', `/projects/${projectId}/portfolio-draft`) })
}

export function usePortfolioActions() {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: sharingKeys.portfolio })
  return {
    create: useMutation({
      mutationFn: (body: S['PortfolioCreate']) => api<Portfolio>('POST', '/portfolio', body),
      onSuccess: refresh,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: string; body: S['PortfolioUpdate'] }) =>
        api<Portfolio>('PATCH', `/portfolio/${id}`, body),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (id: string) => api<void>('DELETE', `/portfolio/${id}`), onSuccess: refresh }),
  }
}

export function usePublicPortfolio(slug: string) {
  return useQuery({
    queryKey: ['public-portfolio', slug],
    queryFn: () => api<PublicPortfolio>('GET', `/public/portfolio/${slug}`),
    retry: false,
  })
}
