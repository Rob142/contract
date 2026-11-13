import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './client'
import { keys as projectKeys, type ProjectDetail } from './projects'
import type { components } from './schema'

type S = components['schemas']
export type RevisionDraft = S['RevisionDraft']
export type RevisionInput = S['RevisionIn']
export type OldTerm = S['OldTerm']

/** 수정 계약 반영 초안 (저장하지 않음) */
export function useRevisionDraft(projectId: string, versionId: string | null) {
  return useQuery({
    queryKey: ['projects', 'revision-draft', projectId, versionId],
    queryFn: () =>
      api<RevisionDraft>('POST', `/projects/${projectId}/revision-draft`, { contract_version_id: versionId }),
    enabled: Boolean(versionId),
    staleTime: 0,
    retry: false,
  })
}

export function useReviseContract(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ body, idempotencyKey }: { body: RevisionInput; idempotencyKey: string }) =>
      api<ProjectDetail>('POST', `/projects/${projectId}/revise-contract`, body, {
        headers: { 'Idempotency-Key': idempotencyKey },
      }),
    onSuccess: (project) => {
      qc.setQueryData(projectKeys.project(projectId), project)
      void qc.invalidateQueries({ queryKey: projectKeys.projects })
      void qc.invalidateQueries({ queryKey: projectKeys.dashboard })
      void qc.invalidateQueries({ queryKey: ['contracts'] })
      void qc.invalidateQueries({ queryKey: ['invoices'] })
    },
  })
}
