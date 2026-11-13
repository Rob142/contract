import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api, ApiError } from './client'
import type { components } from './schema'

export type User = components['schemas']['UserOut']
export type RegisterInput = components['schemas']['RegisterIn']
export type LoginInput = components['schemas']['LoginIn']
export type UserUpdate = components['schemas']['UserUpdate']
export type LlmModelCreateInput = components['schemas']['LlmModelCreate']
export type LlmModelItem = components['schemas']['LlmModelOut']
export type JobType = User['job_type']
export type LlmMode = User['default_llm_mode']

export const meKey = ['me'] as const

async function fetchMe(): Promise<User | null> {
  try {
    return await api<User>('GET', '/users/me')
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null
    throw err
  }
}

/** 로그인한 사용자. 로그인 전이면 null. */
export function useMe() {
  return useQuery({ queryKey: meKey, queryFn: fetchMe, staleTime: 5 * 60_000, retry: false })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: LoginInput) => api<User>('POST', '/auth/login', input),
    onSuccess: (user) => qc.setQueryData(meKey, user),
  })
}

export function useRegister() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: RegisterInput) => api<User>('POST', '/auth/register', input),
    onSuccess: (user) => qc.setQueryData(meKey, user),
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('POST', '/auth/logout'),
    // 실패해도 이 기기에서는 로그아웃 상태로 만든다. 다른 사용자의 데이터가 캐시에 남지 않게 비운다.
    onSettled: () => {
      qc.clear()
      qc.setQueryData(meKey, null)
    },
  })
}

export function useUpdateMe() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (changes: UserUpdate) => api<User>('PATCH', '/users/me', changes),
    onSuccess: (user) => {
      qc.setQueryData(meKey, user)
      void qc.invalidateQueries({ queryKey: ['llm-status'] })
    },
  })
}

export function useAddLlmModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: LlmModelCreateInput) => api<User>('POST', '/users/me/llm-models', body),
    onSuccess: (user) => {
      qc.setQueryData(meKey, user)
      void qc.invalidateQueries({ queryKey: ['llm-status'] })
    },
  })
}

export function useActivateLlmModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (modelId: string) => api<User>('PATCH', `/users/me/llm-models/${modelId}/activate`),
    onSuccess: (user) => {
      qc.setQueryData(meKey, user)
      void qc.invalidateQueries({ queryKey: ['llm-status'] })
    },
  })
}

export function useDeleteLlmModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (modelId: string) => api<User>('DELETE', `/users/me/llm-models/${modelId}`),
    onSuccess: (user) => {
      qc.setQueryData(meKey, user)
      void qc.invalidateQueries({ queryKey: ['llm-status'] })
    },
  })
}

export function useChangePassword() {
  return useMutation({
    mutationFn: (body: { current_password: string; new_password: string }) =>
      api<void>('PATCH', '/users/me/password', body),
  })
}
