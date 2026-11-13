import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { detectContractTransitions } from '../lib/contractEvents'
import { api, ApiError } from './client'
import type { components } from './schema'

type S = components['schemas']
export type ContractSummary = S['ContractSummary']
export type ContractDetail = S['ContractDetail']
export type ContractList = S['ContractList']
export type ContractText = S['ContractText']
export type ContractField = S['FieldOut']
export type FieldKey = ContractField['key']
export type FieldValues = S['FieldValues']
export type VersionStatus = ContractSummary['status']
export type StatusGroup = 'processing' | 'needs_review' | 'ready' | 'analyzed' | 'failed'
export type UploadResult = S['UploadResult']
export type Job = S['JobOut']

const PROCESSING: VersionStatus[] = ['uploaded', 'extracting', 'analyzing']
export const isProcessing = (status: VersionStatus) => PROCESSING.includes(status)

export const contractKeys = {
  all: ['contracts'] as const,
  list: (group: StatusGroup | 'all', q: string) => ['contracts', 'list', group, q] as const,
  detail: (id: string) => ['contracts', 'detail', id] as const,
  text: (id: string) => ['contracts', 'text', id] as const,
}

/** 작업자 처리 중에는 2초마다 상태를 다시 읽는다 (설계서 5장) */
const POLL_MS = 2000

export function useContracts(group: StatusGroup | 'all', q: string) {
  const params = new URLSearchParams({ limit: '100' })
  if (group !== 'all') params.set('group', group)
  if (q) params.set('q', q)
  const query = useQuery({
    queryKey: contractKeys.list(group, q),
    queryFn: () => api<ContractList>('GET', `/contracts?${params.toString()}`),
    refetchInterval: (query) => (query.state.data?.items.some((c) => isProcessing(c.status)) ? POLL_MS : false),
  })
  // 폴링 사이에 끝난 처리를 토스트로 알린다
  useEffect(() => {
    if (query.data) detectContractTransitions(query.data.items)
  }, [query.data])
  return query
}

export function useContract(id: string) {
  const query = useQuery({
    queryKey: contractKeys.detail(id),
    queryFn: () => api<ContractDetail>('GET', `/contracts/${id}`),
    enabled: Boolean(id),
    refetchInterval: (query) => {
      const data = query.state.data
      const jobActive = data?.job && (data.job.status === 'queued' || data.job.status === 'running')
      return data && (isProcessing(data.status) || jobActive) ? POLL_MS : false
    },
    // 앱이 뒤로 가 있으면 폴링하지 않는다
    refetchIntervalInBackground: false,
  })
  useEffect(() => {
    if (query.data) detectContractTransitions([query.data])
  }, [query.data])
  return query
}

export function useContractText(id: string, enabled: boolean) {
  return useQuery({
    queryKey: contractKeys.text(id),
    queryFn: () => api<ContractText>('GET', `/contracts/${id}/text`),
    enabled,
    staleTime: Infinity, // 추출 결과는 버전마다 고정
  })
}

export function contractFileUrl(id: string, download = false) {
  return `/api/v1/contracts/${id}/file${download ? '?download=true' : ''}`
}

/** 업로드 진행률을 보여주려고 fetch 대신 XHR을 쓴다 */
export function uploadContract(
  file: File,
  onProgress: (ratio: number) => void,
  signal?: AbortSignal,
  /** 있으면 그 계약의 새 버전(수정 계약서)으로 올린다 */
  contractId?: string,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', contractId ? `/api/v1/contracts/${contractId}/versions` : '/api/v1/contracts')
    xhr.withCredentials = true
    xhr.responseType = 'json'
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
    xhr.onload = () => {
      const body = xhr.response as { error?: { code?: string; message?: string; details?: unknown } } | null
      if (xhr.status >= 200 && xhr.status < 300) return resolve(xhr.response as UploadResult)
      reject(new ApiError(xhr.status, body?.error?.code ?? 'http_error', body?.error?.message ?? '', body?.error?.details))
    }
    xhr.onerror = () => reject(new ApiError(0, 'network_error', 'network request failed'))
    xhr.onabort = () => reject(new DOMException('aborted', 'AbortError'))
    signal?.addEventListener('abort', () => xhr.abort())
    const form = new FormData()
    form.append('file', file)
    xhr.send(form)
  })
}

export function useUpdateFields(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { values: FieldValues; confirm: boolean }) =>
      api<ContractDetail>('PATCH', `/contracts/${id}/fields`, body),
    onSuccess: (detail) => {
      qc.setQueryData(contractKeys.detail(id), detail)
      void qc.invalidateQueries({ queryKey: ['contracts', 'list'] })
    },
  })
}

export function useRetryExtract(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<UploadResult>('POST', `/contracts/${id}/extract`),
    onSuccess: (result) => {
      qc.setQueryData(contractKeys.detail(id), result.contract)
      qc.removeQueries({ queryKey: contractKeys.text(id) })
      void qc.invalidateQueries({ queryKey: ['contracts', 'list'] })
    },
  })
}

export function useCancelJob(contractId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => api<Job>('POST', `/jobs/${jobId}/cancel`),
    onSettled: () => void qc.invalidateQueries({ queryKey: contractKeys.detail(contractId) }),
  })
}

export function useDeleteContract(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('DELETE', `/contracts/${id}`),
    onSuccess: () => {
      qc.removeQueries({ queryKey: contractKeys.detail(id) })
      qc.removeQueries({ queryKey: contractKeys.text(id) })
      void qc.invalidateQueries({ queryKey: ['contracts', 'list'] })
    },
  })
}

export function useUpdateContract(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: S['ContractUpdate']) => api<ContractDetail>('PATCH', `/contracts/${id}`, body),
    onSuccess: (detail) => {
      qc.setQueryData(contractKeys.detail(id), detail)
      void qc.invalidateQueries({ queryKey: ['contracts', 'list'] })
    },
  })
}
