import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react'

interface FieldShellProps {
  label: string
  error?: string
  hint?: ReactNode
  className?: string
  children: (ids: { inputId: string; describedBy: string | undefined }) => ReactNode
}

function FieldShell({ label, error, hint, className, children }: FieldShellProps) {
  const inputId = useId()
  const messageId = `${inputId}-message`
  return (
    <div className={['field', className].filter(Boolean).join(' ')}>
      <label className="field-label" htmlFor={inputId}>
        {label}
      </label>
      {children({ inputId, describedBy: error || hint ? messageId : undefined })}
      {error ? (
        <span id={messageId} className="field-error" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span id={messageId} className="field-hint">
          {hint}
        </span>
      ) : null}
    </div>
  )
}

type TextFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string
  error?: string
  hint?: ReactNode
  fieldClassName?: string
}

export function TextField({ label, error, hint, fieldClassName, ...input }: TextFieldProps) {
  return (
    <FieldShell label={label} error={error} hint={hint} className={fieldClassName}>
      {({ inputId, describedBy }) => (
        <input
          id={inputId}
          className="input"
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...input}
        />
      )}
    </FieldShell>
  )
}

type SelectFieldProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label: string
  options: { value: string; label: string }[]
  error?: string
  hint?: ReactNode
  fieldClassName?: string
}

export function SelectField({ label, options, error, hint, fieldClassName, ...select }: SelectFieldProps) {
  return (
    <FieldShell label={label} error={error} hint={hint} className={fieldClassName}>
      {({ inputId, describedBy }) => (
        <select
          id={inputId}
          className="input"
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          {...select}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </FieldShell>
  )
}
