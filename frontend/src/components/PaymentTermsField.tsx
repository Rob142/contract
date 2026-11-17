import { useState } from 'react'
import { TextField } from './Field'

const PRESETS = [
  '계약 체결 후 선금 50% · 검수 완료 후 잔금 50%',
  '계약 체결 후 선금 30% · 중간 검수 후 중도금 40% · 최종 검수 후 잔금 30%',
  '착수 전 전액 지급',
  '최종 검수 완료 후 전액 지급',
]

export function PaymentTermsField({ value, onChange, maxLength = 200 }: { value: string; onChange: (value: string) => void; maxLength?: number }) {
  const [mode, setMode] = useState('custom')
  return (
    <fieldset className="consent-group">
      <legend>지급 조건</legend>
      <p className="field-hint">바로 직접 입력할 수 있어요. 예시를 선택할 때는 실제 계약 내용과 일치하는지 확인하세요.</p>
      <div className="payment-presets">
        <label className="checkbox"><input type="radio" name="payment-mode" checked={mode === 'custom'} onChange={() => setMode('custom')} />직접 입력</label>
        {PRESETS.map((preset) => <label className="checkbox" key={preset}>
          <input type="radio" name="payment-mode" checked={mode === preset} onChange={() => { setMode(preset); onChange(preset) }} />{preset}
        </label>)}
      </div>
      <TextField label="실제 계약의 지급 조건" value={value} maxLength={maxLength} onChange={(e) => { setMode('custom'); onChange(e.target.value) }} hint="선택한 예시도 아래에서 수정할 수 있어요. 계약서에 없는 조건을 추가하지 마세요." />
    </fieldset>
  )
}
