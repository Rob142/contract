import type { VersionStatus } from '../api/contracts'

export const STATUS_BADGE: Record<VersionStatus, { label: string; className: string }> = {
  uploaded: { label: '추출 대기', className: 'badge badge-blue' },
  extracting: { label: '텍스트 추출 중', className: 'badge badge-blue' },
  needs_review: { label: '텍스트 확인 필요', className: 'badge badge-amber' },
  ready: { label: '확인 완료', className: 'badge badge-green' },
  analyzing: { label: '분석 중', className: 'badge badge-blue' },
  analyzed: { label: '분석 완료', className: 'badge badge-green' },
  failed: { label: '처리 실패', className: 'badge badge-red' },
}

export const FAILURE_REASONS: Record<string, string> = {
  no_text: '읽을 수 있는 글자를 찾지 못했어요. 스캔 상태를 확인하고 다시 올려 주세요.',
  no_text_ocr_disabled: '글자 정보가 없는 스캔 문서예요. 현재 OCR이 꺼져 있어 읽을 수 없어요.',
  cancelled: '추출을 취소했어요.',
  worker_stopped: '처리하던 작업자가 멈췄어요. 다시 시도해 주세요.',
  timeout: '처리 시간이 너무 오래 걸려 멈췄어요. 페이지 수를 줄여 다시 올려 주세요.',
  ocr_error: 'OCR 처리 중 오류가 났어요. 다시 시도해 주세요.',
  internal_error: '처리 중 오류가 났어요. 다시 시도해 주세요.',
  file_missing: '원본 파일을 찾을 수 없어요. 다시 업로드해 주세요.',
}

export function failureMessage(reason: string | null | undefined): string {
  return (reason && FAILURE_REASONS[reason]) || '처리하지 못했어요. 다시 시도해 주세요.'
}

export const JOB_STAGE_LABELS: Record<string, string> = {
  extracting: '페이지별 텍스트를 읽고 있어요',
  ocr: '스캔 페이지를 OCR로 읽고 있어요',
  validating: '추출 결과를 정리하고 있어요',
}

export const FIELD_LABELS = {
  contract_amount: '계약 금액',
  final_due_date: '최종 납기',
  payment_terms: '지급 조건',
  revision_count: '수정 횟수',
} as const
