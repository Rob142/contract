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
      hint="직업군에 맞는 규칙(예: 디자인은 수정 횟수·저작권)으로 검토해요."
    />
  )
}
