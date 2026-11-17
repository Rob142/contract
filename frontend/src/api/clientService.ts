import { useQuery } from '@tanstack/react-query'
import { api } from './client'

export const cs = <T>(
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  path: string,
  body?: unknown,
) => api<T>(method, `/client-service${path}`, body)
export const useCS = <T>(path: string, enabled = true) =>
  useQuery({
    queryKey: ['client-service', path],
    queryFn: () => cs<T>('GET', path),
    enabled,
    retry: false,
  })
export type Workspace = { id: string; name: string; role: string }
export type Member = { id: string; name: string; email: string; role: string }
export type Grant = {
  id: string
  name: string
  can_finance: boolean
  approver: boolean
}
export type Work = {
  title: string
  description: string
  contribution: string
  url: string
  image_url?: string | null
  client_name: string
  feedback: string
  assets_consent: boolean
  client_name_consent: boolean
  feedback_consent: boolean
}
export type Profile = {
  id: string
  name: string
  published?: boolean
  headline: string
  bio: string
  job_type: string
  services: string[]
  scope: string
  price: string | null
  price_type: string
  vat: string
  exclusions: string
  revisions: number
  days: number | null
  available_from: string | null
  originals: string
  rights: string
  portfolio: Work[]
  reasons?: string[]
}
export type Review = {
  id: string
  kind: string
  body: string
  actor_name: string
  workspace_name: string
  created_at: string
}
export type Delivery = {
  id: string
  delivery_id: string
  title: string
  seq: number
  current: boolean
  state: string
  due_date: string | null
  created_at: string
  payload: {
    note: string
    attachments: {
      id: string
      title: string
      url: string | null
      has_file: boolean
    }[]
  }
  events: Review[]
}
export type ClientTask = {
  id: string
  title: string
  due_date: string | null
  status: 'todo' | 'doing' | 'done'
  client_visible: boolean
  label?: string | null
}
export type ClientProject = {
  id: string
  name: string
  status: string
  due_date: string | null
  owner: boolean
  workspace_id: string | null
  approver_id: string | null
  can_manage: boolean
  can_write: boolean
  can_approve: boolean
  can_finance: boolean
  contract_amount: string | null
  freelancer_name: string
  tasks: ClientTask[]
  deliveries: Delivery[]
  revisions: {
    included: number | null
    used: number
    remaining: number | null
  }
  extra_quotes: {
    id: string
    title: string
    description: string | null
    amount: string
    accepted: boolean
  }[]
  agreement?: {
    seq: number
    payload: QuotePayload
    accepted_at: string
  } | null
}
export type QuotePayload = {
  amount: string
  vat: string
  scope: string
  deliverables: string
  exclusions: string
  revisions: number
  due_date: string
  client_due_date: string
  payment: string
  rights: string
  originals: string
}
export type Inquiry = {
  id: string
  workspace_id: string
  freelancer_id: string
  freelancer_name: string
  creator_id: string
  client_name: string
  status: string
  project_id: string | null
  payload: {
    title: string
    purpose: string
    scope: string
    deliverables: string
    budget: string | null
    due_date: string | null
    references: string
  }
  quotes: {
    id: string
    seq: number
    payload: QuotePayload
    accepted_at: string | null
  }[]
  messages: {
    id: string
    actor_name: string
    body: string
    created_at: string
  }[]
}
export type Invitation = {
  id: string
  email: string
  role: string
  expires_at: string
  used_at: string | null
  revoked_at: string | null
  mail_status: string
  token?: string
}
