import type { JobType } from '../api/auth'
import { useUpdateContract, type ContractDetail } from '../api/contracts'
import { messageOf } from '../api/messages'
import { JOB_TYPE_LABELS } from '../lib/format'
import { SelectField } from './Field'

const OPTIONS = Object.entries(JOB_TYPE_LABELS).map(([value, label]) => ({ value, label }))

/** 계약서의 직업군. 분석 규칙을 정하므로 계약서마다 고르고, 확인·분석 화면이 같은 값을 쓴다 */
export function JobTypeSelect({ contract, label = '이 계약서의 직업군' }: { contract: ContractDetail; label?: string }) {
  const update = useUpdateContract(contract.id)
  return (
    <SelectField
      label={label}
      options={OPTIONS}
      value={contract.job_type}
      disabled={update.isPending || contract.status === 'analyzing'}
      onChange={(e) => update.mutate({ job_type: e.target.value as JobType })}
      error={update.isError ? messageOf(update.error) : undefined}
      hint={['dev', 'design', 'video', 'marketing'].includes(contract.job_type)
        ? '직업군별 규칙과 공통 계약 규칙으로 검토해요.'
        : '현재 이 직군은 대금·납기·권리 등 공통 계약 규칙으로 검토해요. 직군별 추가 규칙은 아직 제공하지 않아요.'}
    />
  )
}
