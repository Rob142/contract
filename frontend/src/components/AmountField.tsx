import { TextField } from './Field'
import { digitsOnly, groupDigits } from '../lib/format'

interface AmountFieldProps {
  label: string
  /** 숫자만 담긴 문자열 ("1000000"). 서버에도 문자열 그대로 보낸다 */
  value: string
  onChange: (digits: string) => void
  error?: string
  fieldClassName?: string
}

const MAX_DIGITS = 14

/** 원 단위 금액 입력. 화면에는 쉼표를 넣어 보여주고 값은 숫자 문자열로 다룬다. */
export function AmountField({ label, value, onChange, error, fieldClassName }: AmountFieldProps) {
  return (
    <TextField
      label={label}
      inputMode="numeric"
      autoComplete="off"
      placeholder="0"
      value={value ? `${groupDigits(value)} 원` : ''}
      onChange={(e) => onChange(digitsOnly(e.target.value).slice(0, MAX_DIGITS))}
      error={error}
      fieldClassName={fieldClassName}
    />
  )
}
