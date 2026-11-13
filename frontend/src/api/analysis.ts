import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'
import { contractKeys } from './contracts'
import type { components } from './schema'

type S = components['schemas']
export type LlmStatus = S['LlmStatus']
export type LlmTestInput = S['LlmTestIn']
export type LlmTestOutput = S['LlmTestOut']
export type AnalysisView = S['AnalysisView']
export type Analysis = S['AnalysisOut']
export type AnalysisResult = S['ResultOut']
export type AnalyzeInput = S['AnalyzeIn']

export const analysisKeys = {
  status: ['llm-status'] as const,
  view: (contractId: string) => ['contracts', 'analysis', contractId] as const,
}

export function useLlmStatus() {
  return useQuery({ queryKey: analysisKeys.status, queryFn: () => api<LlmStatus>('GET', '/llm/status'), staleTime: 60_000 })
}

export function useTestLlm() {
  return useMutation({
    mutationFn: (body: LlmTestInput) => api<LlmTestOutput>('POST', '/llm/test', body),
  })
}

/** 분석 작업이 대기·실행 중이면 2초마다 다시 읽는다 */
export function useAnalysis(contractId: string) {
  return useQuery({
    queryKey: analysisKeys.view(contractId),
    queryFn: () => api<AnalysisView>('GET', `/contracts/${contractId}/analysis`),
    refetchInterval: (query) => {
      const status = query.state.data?.latest_job?.status
      return status === 'queued' || status === 'running' ? 2000 : false
    },
    refetchIntervalInBackground: false,
  })
}

export function useRequestAnalysis(contractId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AnalyzeInput) => api<S['AnalyzeOut']>('POST', `/contracts/${contractId}/analyze`, body),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: analysisKeys.view(contractId) })
      void qc.invalidateQueries({ queryKey: contractKeys.detail(contractId) })
      void qc.invalidateQueries({ queryKey: ['contracts', 'list'] })
    },
  })
}

export function useRevisionPrompt(contractId: string) {
  return useMutation({
    mutationFn: (resultIds: string[]) =>
      api<S['RevisionPromptOut']>('POST', `/contracts/${contractId}/revision-prompt`, { result_ids: resultIds }),
  })
}
