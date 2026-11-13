import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { api } from './client'
import type { components } from './schema'

type S = components['schemas']
export type Dashboard = S['Dashboard']
export type ProjectSummary = S['ProjectSummary']
export type ProjectDetail = S['ProjectDetail']
export type ProjectList = S['ProjectList']
export type ProjectStatus = ProjectSummary['status']
export type ProjectCreate = S['ProjectCreate']
export type ProjectUpdate = S['ProjectUpdate']
export type Client = S['ClientOut']
export type Task = S['TaskOut']
export type TaskStatus = Task['status']
export type TaskCreate = S['TaskCreate']
export type TaskUpdate = S['TaskUpdate']
export type ChecklistItem = S['ChecklistItemOut']

export const keys = {
  dashboard: ['dashboard'] as const,
  projects: ['projects'] as const,
  projectList: (status: ProjectStatus | 'all') => ['projects', 'list', status] as const,
  project: (id: string) => ['projects', 'detail', id] as const,
  tasks: (projectId: string) => ['projects', 'tasks', projectId] as const,
  clients: ['clients'] as const,
}

/** 작업이 바뀌면 진행률·대시보드 지표도 바뀐다 */
function invalidateProjectViews(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: keys.projects })
  void qc.invalidateQueries({ queryKey: keys.dashboard })
}

// ---------------------------------------------------------------- 조회
export function useDashboard() {
  return useQuery({ queryKey: keys.dashboard, queryFn: () => api<Dashboard>('GET', '/dashboard') })
}

export function useProjects(status: ProjectStatus | 'all') {
  return useQuery({
    queryKey: keys.projectList(status),
    queryFn: () => api<ProjectList>('GET', `/projects?limit=100${status === 'all' ? '' : `&status=${status}`}`),
  })
}

export function useProject(id: string, enabled = true) {
  return useQuery({ queryKey: keys.project(id), queryFn: () => api<ProjectDetail>('GET', `/projects/${id}`), enabled })
}

export function useTasks(projectId: string) {
  return useQuery({ queryKey: keys.tasks(projectId), queryFn: () => api<Task[]>('GET', `/projects/${projectId}/tasks`) })
}

export function useClients() {
  return useQuery({ queryKey: keys.clients, queryFn: () => api<Client[]>('GET', '/clients') })
}

// ---------------------------------------------------------------- 프로젝트
export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ProjectCreate) => api<ProjectDetail>('POST', '/projects', body),
    onSuccess: (project) => {
      qc.setQueryData(keys.project(project.id), project)
      invalidateProjectViews(qc)
      void qc.invalidateQueries({ queryKey: keys.clients })
    },
  })
}

export function useUpdateProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ProjectUpdate) => api<ProjectDetail>('PATCH', `/projects/${id}`, body),
    onSuccess: (project) => {
      qc.setQueryData(keys.project(id), project)
      invalidateProjectViews(qc)
    },
  })
}

export function useDeleteProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<void>('DELETE', `/projects/${id}`),
    onSuccess: () => {
      qc.removeQueries({ queryKey: keys.project(id) })
      qc.removeQueries({ queryKey: keys.tasks(id) })
      invalidateProjectViews(qc)
    },
  })
}

// ---------------------------------------------------------------- 작업
export function useCreateTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TaskCreate) => api<Task>('POST', `/projects/${projectId}/tasks`, body),
    onSuccess: (task) => {
      qc.setQueryData<Task[]>(keys.tasks(projectId), (old) => [...(old ?? []), task])
      invalidateProjectViews(qc)
    },
  })
}

export function useUpdateTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, ...body }: TaskUpdate & { id: string }) => api<Task>('PATCH', `/tasks/${id}`, body),
    onSuccess: (task) => {
      qc.setQueryData<Task[]>(keys.tasks(projectId), (old) => old?.map((t) => (t.id === task.id ? task : t)))
      invalidateProjectViews(qc)
    },
  })
}

export function useDeleteTask(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>('DELETE', `/tasks/${id}`),
    onSuccess: (_, id) => {
      qc.setQueryData<Task[]>(keys.tasks(projectId), (old) => old?.filter((t) => t.id !== id))
      invalidateProjectViews(qc)
    },
  })
}

/** 열 안에서의 순서를 바꾼 목록 (서버 move_task와 같은 규칙) */
export function applyMove(tasks: Task[], taskId: string, status: TaskStatus, index: number): Task[] {
  const moving = tasks.find((t) => t.id === taskId)
  if (!moving) return tasks
  const target = tasks.filter((t) => t.status === status && t.id !== taskId)
  target.splice(Math.min(index, target.length), 0, { ...moving, status })
  const positioned = new Map(target.map((t, position) => [t.id, { ...t, position }]))
  const rest = tasks.filter((t) => t.id !== taskId && !positioned.has(t.id))
  return [...rest, ...positioned.values()]
}

export function useMoveTask(projectId: string) {
  const qc = useQueryClient()
  const key = keys.tasks(projectId)
  return useMutation({
    mutationFn: ({ taskId, status, index }: { taskId: string; status: TaskStatus; index: number }) =>
      api<Task[]>('POST', `/tasks/${taskId}/move`, { status, index }),
    // 끌어다 놓는 즉시 화면에 반영하고, 실패하면 되돌린다
    onMutate: async ({ taskId, status, index }) => {
      await qc.cancelQueries({ queryKey: key })
      const previous = qc.getQueryData<Task[]>(key)
      if (previous) qc.setQueryData(key, applyMove(previous, taskId, status, index))
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) qc.setQueryData(key, context.previous)
    },
    onSuccess: (tasks) => {
      qc.setQueryData(key, tasks)
      invalidateProjectViews(qc)
    },
  })
}

// ---------------------------------------------------------------- 체크리스트
function replaceChecklist(qc: QueryClient, projectId: string, taskId: string, fn: (items: ChecklistItem[]) => ChecklistItem[]) {
  qc.setQueryData<Task[]>(keys.tasks(projectId), (old) =>
    old?.map((t) => (t.id === taskId ? { ...t, checklist: fn(t.checklist) } : t)),
  )
}

export function useAddChecklistItem(projectId: string, taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (content: string) => api<ChecklistItem>('POST', `/tasks/${taskId}/checklist`, { content }),
    onSuccess: (item) => replaceChecklist(qc, projectId, taskId, (items) => [...items, item]),
  })
}

export function useToggleChecklistItem(projectId: string, taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, is_done }: { id: string; is_done: boolean }) =>
      api<ChecklistItem>('PATCH', `/checklist-items/${id}`, { is_done }),
    onSuccess: (item) => replaceChecklist(qc, projectId, taskId, (items) => items.map((i) => (i.id === item.id ? item : i))),
  })
}

export function useDeleteChecklistItem(projectId: string, taskId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api<void>('DELETE', `/checklist-items/${id}`),
    onSuccess: (_, id) => replaceChecklist(qc, projectId, taskId, (items) => items.filter((i) => i.id !== id)),
  })
}

/** 프로젝트에서 계약서를 떼어 낸다. 청구 이력이 있으면 서버가 막는다 */
export function useUnlinkContract(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api<ProjectDetail>('DELETE', `/projects/${id}/contract`),
    onSuccess: (project) => {
      qc.setQueryData(keys.project(id), project)
      invalidateProjectViews(qc)
      void qc.invalidateQueries({ queryKey: ['contracts'] })
    },
  })
}
