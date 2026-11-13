import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import type { JobType } from '../api/auth'
import { fieldErrorsOf } from '../api/client'
import { messageOf } from '../api/messages'
import {
  useClients,
  useCreateProject,
  useDeleteProject,
  useUpdateProject,
  type ProjectDetail,
  type ProjectStatus,
} from '../api/projects'
import { JOB_TYPE_LABELS } from '../lib/format'
import { AmountField } from './AmountField'
import { Dialog } from './Dialog'
import { SelectField, TextField } from './Field'

const NEW_CLIENT = '__new__'
const JOB_OPTIONS = Object.entries(JOB_TYPE_LABELS).map(([value, label]) => ({ value, label }))
const STATUS_OPTIONS = [
  { value: 'active', label: '진행 중' },
  { value: 'completed', label: '완료' },
  { value: 'archived', label: '보관' },
]

type FormState = {
  name: string
  clientChoice: string
  newClientName: string
  jobType: JobType
  startDate: string
  dueDate: string
  amount: string
  status: ProjectStatus
}

function validate(f: FormState): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!f.name.trim()) errors.name = '프로젝트명을 입력해 주세요.'
  if (f.clientChoice === NEW_CLIENT && !f.newClientName.trim()) errors.client = '거래처 이름을 입력해 주세요.'
  if (!f.clientChoice) errors.client = '거래처를 선택해 주세요.'
  if (f.startDate && f.dueDate && f.dueDate < f.startDate) errors.due_date = '최종 납기는 시작일 이후여야 해요.'
  return errors
}

interface ProjectFormProps {
  title: string
  initial: FormState
  project?: ProjectDetail
  onClose: () => void
}

function ProjectFormDialog({ title, initial, project, onClose }: ProjectFormProps) {
  const navigate = useNavigate()
  const clients = useClients()
  const create = useCreateProject()
  const update = useUpdateProject(project?.id ?? '')
  const remove = useDeleteProject(project?.id ?? '')
  const [form, setForm] = useState(initial)
  const [touched, setTouched] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const mutation = project ? update : create
  const clientErrors = validate(form)
  const serverErrors = fieldErrorsOf(mutation.error)
  const errors = touched ? clientErrors : {}
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }))

  const clientOptions = [
    ...(clients.data ?? []).map((c) => ({ value: c.id, label: c.name })),
    { value: NEW_CLIENT, label: '+ 새 거래처 입력' },
  ]

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (Object.keys(clientErrors).length > 0) return

    const common = {
      name: form.name.trim(),
      job_type: form.jobType,
      start_date: form.startDate || null,
      due_date: form.dueDate || null,
      contract_amount: form.amount || '0',
    }
    const clientPart =
      form.clientChoice === NEW_CLIENT ? { new_client_name: form.newClientName.trim() } : { client_id: form.clientChoice }

    if (project) {
      // 수정 화면에서는 기존 거래처만 고른다. version으로 동시 수정을 감지한다
      update.mutate(
        { ...common, client_id: form.clientChoice, status: form.status, version: project.version },
        { onSuccess: onClose },
      )
    } else {
      create.mutate({ ...common, ...clientPart }, { onSuccess: (p) => navigate(`/projects/${p.id}`) })
    }
  }

  const onDelete = () => {
    remove.mutate(undefined, { onSuccess: () => navigate('/projects', { replace: true }) })
  }

  const footer = (
    <>
      {project && (
        <button
          type="button"
          className="btn btn-danger-text"
          onClick={() => (confirmDelete ? onDelete() : setConfirmDelete(true))}
          disabled={remove.isPending}
        >
          {confirmDelete ? '정말 삭제할까요?' : '프로젝트 삭제'}
        </button>
      )}
      <span className="spacer" />
      <button type="button" className="btn btn-secondary" onClick={onClose}>
        취소
      </button>
      <button type="submit" form="project-form" className="btn btn-primary" disabled={mutation.isPending}>
        {mutation.isPending ? '저장 중…' : project ? '저장' : '프로젝트 만들기'}
      </button>
    </>
  )

  return (
    <Dialog open onClose={onClose} title={title} footer={footer}>
      <form id="project-form" className="form-grid" onSubmit={onSubmit} noValidate>
        <TextField
          label="프로젝트명"
          value={form.name}
          onChange={(e) => set('name', e.target.value)}
          maxLength={100}
          error={errors.name}
          fieldClassName="span-2"
          autoFocus
        />
        <SelectField
          label="거래처"
          options={project ? clientOptions.filter((o) => o.value !== NEW_CLIENT) : clientOptions}
          value={form.clientChoice}
          onChange={(e) => set('clientChoice', e.target.value)}
          error={form.clientChoice === NEW_CLIENT ? undefined : errors.client}
        />
        <SelectField
          label="직업군"
          options={JOB_OPTIONS}
          value={form.jobType}
          onChange={(e) => set('jobType', e.target.value as JobType)}
        />
        {form.clientChoice === NEW_CLIENT && (
          <TextField
            label="새 거래처 이름"
            value={form.newClientName}
            onChange={(e) => set('newClientName', e.target.value)}
            maxLength={100}
            error={errors.client}
            fieldClassName="span-2"
          />
        )}
        <TextField label="시작일" type="date" value={form.startDate} onChange={(e) => set('startDate', e.target.value)} />
        <TextField
          label="최종 납기"
          type="date"
          value={form.dueDate}
          min={form.startDate || undefined}
          onChange={(e) => set('dueDate', e.target.value)}
          error={errors.due_date}
        />
        <AmountField
          label="계약 금액"
          value={form.amount}
          onChange={(v) => set('amount', v)}
          error={serverErrors.contract_amount ? '금액을 확인해 주세요.' : undefined}
          fieldClassName={project ? undefined : 'span-2'}
        />
        {project && (
          <SelectField
            label="상태"
            options={STATUS_OPTIONS}
            value={form.status}
            onChange={(e) => set('status', e.target.value as ProjectStatus)}
          />
        )}
      </form>
      {(mutation.isError || remove.isError) && (
        <div className="alert alert-error" role="alert" style={{ marginTop: 16 }}>
          {messageOf(mutation.error ?? remove.error)}
        </div>
      )}
    </Dialog>
  )
}

export function NewProjectDialog({ defaultJobType, onClose }: { defaultJobType: JobType; onClose: () => void }) {
  const clients = useClients()
  const firstClient = clients.data?.[0]?.id
  return (
    <ProjectFormDialog
      key={clients.isSuccess ? 'ready' : 'loading'}
      title="새 프로젝트"
      onClose={onClose}
      initial={{
        name: '',
        clientChoice: firstClient ?? NEW_CLIENT,
        newClientName: '',
        jobType: defaultJobType,
        startDate: '',
        dueDate: '',
        amount: '',
        status: 'active',
      }}
    />
  )
}

export function EditProjectDialog({ project, onClose }: { project: ProjectDetail; onClose: () => void }) {
  return (
    <ProjectFormDialog
      title="프로젝트 수정"
      project={project}
      onClose={onClose}
      initial={{
        name: project.name,
        clientChoice: project.client.id,
        newClientName: '',
        jobType: project.job_type,
        startDate: project.start_date ?? '',
        dueDate: project.due_date ?? '',
        amount: project.contract_amount === '0' ? '' : project.contract_amount,
        status: project.status,
      }}
    />
  )
}
