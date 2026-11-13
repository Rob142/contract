import { useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { ApiError } from '../api/client'
import { contractKeys, uploadContract } from '../api/contracts'
import { messageOf } from '../api/messages'

/** 수정 계약서를 같은 계약의 새 버전으로 올리고 그 계약서 화면(조건 확인)으로 간다 */
export function UploadVersionButton({
  contractId,
  label = '수정 계약서 올리기',
  className = 'btn btn-secondary',
}: {
  contractId: string
  label?: string
  className?: string
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const onFile = async (file: File | undefined) => {
    if (!file) return
    setError(null)
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') return setError('PDF 파일만 올릴 수 있어요.')
    setProgress(0)
    try {
      await uploadContract(file, setProgress, undefined, contractId)
      void qc.invalidateQueries({ queryKey: contractKeys.all })
      navigate(`/contracts/${contractId}`)
    } catch (err) {
      setError(err instanceof ApiError ? messageOf(err) : '업로드하지 못했어요.')
    } finally {
      setProgress(null)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        hidden
        aria-label={label}
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      <button type="button" className={className} disabled={progress !== null} onClick={() => inputRef.current?.click()}>
        {progress !== null ? `올리는 중 ${Math.round(progress * 100)}%` : label}
      </button>
      {error && (
        <span className="field-error small" role="alert">
          {error}
        </span>
      )}
    </>
  )
}
