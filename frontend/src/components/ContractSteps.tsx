import { Link } from 'react-router'

import type { ContractDetail } from '../api/contracts'
import { JOB_TYPE_LABELS } from '../lib/format'

export const CONFIRMED_STATUSES = ['ready', 'analyzing', 'analyzed'] as const
export const isConfirmed = (status: ContractDetail['status']) =>
  (CONFIRMED_STATUSES as readonly string[]).includes(status)

type StepState = 'done' | 'current' | 'locked' | 'optional'

/** 계약서 상세 상단 진행 표시: ① 조건 확인 → ② AI 분석(선택) → ③ 프로젝트. 단계마다 다음 행동을 바로 연다 */
export function ContractSteps({
  contract,
  hasAnalysis,
  targetProjectId,
}: {
  contract: ContractDetail
  hasAnalysis: boolean
  /** 프로젝트 화면에서 계약서를 올리러 왔을 때 그 프로젝트 */
  targetProjectId?: string | null
}) {
  const confirmed = isConfirmed(contract.status)
  const analyzing = contract.status === 'analyzing'
  const hasProject = Boolean(contract.project_id)
  // 프로젝트가 이 계약의 이전 버전을 쓰고 있다 = 수정 계약 반영 전
  const pendingRevision = hasProject && (contract.project_version_no ?? contract.version_no) < contract.version_no

  const steps: { title: string; state: StepState; detail: string; action?: { to: string; label: string } }[] = [
    {
      title: '조건 확인',
      state: confirmed ? 'done' : contract.status === 'needs_review' ? 'current' : 'locked',
      detail: confirmed
        ? `확인 완료 · ${JOB_TYPE_LABELS[contract.job_type]} 계약`
        : contract.status === 'needs_review'
          ? '금액·납기·지급 조건을 원문과 비교해 확정하세요'
          : '텍스트 추출이 끝나면 시작해요',
    },
    {
      title: 'AI 분석 (선택)',
      state: hasAnalysis ? 'done' : !confirmed ? 'locked' : hasProject ? 'optional' : 'current',
      detail: hasAnalysis
        ? '분석 완료 · 협의할 조건을 확인하세요'
        : analyzing
          ? '분석하고 있어요'
          : confirmed
            ? '빠진 조건·위험한 조항을 찾아줘요'
            : '조건 확인을 마치면 열려요',
      action: hasAnalysis ? { to: `/contracts/${contract.id}/analysis`, label: '결과 보기' } : undefined,
    },
    {
      title: '프로젝트',
      state: pendingRevision
        ? confirmed
          ? 'current'
          : 'locked'
        : hasProject
          ? 'done'
          : confirmed
            ? hasAnalysis
              ? 'current'
              : 'optional'
            : 'locked',
      detail: pendingRevision
        ? confirmed
          ? `프로젝트는 v${contract.project_version_no}을 쓰고 있어요. 청구 이력을 이어 붙여 반영하세요`
          : '조건 확인을 마치면 프로젝트에 반영할 수 있어요'
        : hasProject
        ? '프로젝트로 일정·청구를 관리해요'
        : confirmed
          ? '새 프로젝트를 만들거나 기존 프로젝트에 연결해요'
          : '조건 확인을 마치면 열려요',
      action: pendingRevision
        ? confirmed
          ? { to: `/projects/${contract.project_id}/revise?version=${contract.version_id}`, label: '수정 계약 반영' }
          : { to: `/projects/${contract.project_id}`, label: '프로젝트 보기' }
        : hasProject
        ? { to: `/projects/${contract.project_id}`, label: '프로젝트 보기' }
        : confirmed
          ? targetProjectId
            ? { to: `/contracts/${contract.id}/project?project=${targetProjectId}`, label: '프로젝트에 연결' }
            : { to: `/contracts/${contract.id}/project`, label: '프로젝트 만들기 · 연결' }
          : undefined,
    },
  ]

  return (
    <ol className="contract-steps" aria-label="계약서 진행 단계">
      {steps.map((step, i) => (
        <li key={step.title} className={`step-${step.state}`} aria-current={step.state === 'current' ? 'step' : undefined}>
          <span className="step-index" aria-hidden="true">
            {step.state === 'done' ? '✓' : i + 1}
          </span>
          <div className="step-body">
            <strong>{step.title}</strong>
            <span className="muted small">{step.detail}</span>
          </div>
          {step.action && (
            <Link to={step.action.to} className={step.state === 'done' ? 'btn btn-secondary' : 'btn btn-primary'}>
              {step.action.label}
            </Link>
          )}
        </li>
      ))}
    </ol>
  )
}
