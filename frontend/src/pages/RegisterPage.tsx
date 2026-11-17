import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'

import { useRegister, type JobType } from '../api/auth'
import { ApiError, fieldErrorsOf } from '../api/client'
import { messageOf } from '../api/messages'
import { SelectField, TextField } from '../components/Field'
import { JOB_TYPE_LABELS } from '../lib/format'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const PASSWORD_MIN = 8

const JOB_OPTIONS = Object.entries(JOB_TYPE_LABELS).map(([value, label]) => ({ value, label }))

// 서버 검증 메시지(영문) 대신 쓰는 필드별 안내
const FIELD_MESSAGES: Record<string, string> = {
  name: '이름을 입력해 주세요.',
  email: '올바른 이메일 형식이 아니에요.',
  password: `비밀번호는 ${PASSWORD_MIN}자 이상이어야 해요.`,
  job_type: '직업군을 선택해 주세요.',
}

/** 02 회원가입. 가입하면 바로 로그인되고 GuestOnly가 대시보드로 보낸다. */
export function RegisterPage() {
  const register = useRegister()
  const [searchParams] = useSearchParams()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [jobType, setJobType] = useState<JobType>('design')
  const [agreeTerms, setAgreeTerms] = useState(false)
  const [agreePrivacy, setAgreePrivacy] = useState(false)
  const agree = agreeTerms && agreePrivacy
  const [touched, setTouched] = useState(false)

  const clientErrors: Record<string, string> = {}
  if (!name.trim()) clientErrors.name = FIELD_MESSAGES.name!
  if (!EMAIL_RE.test(email.trim())) clientErrors.email = FIELD_MESSAGES.email!
  if (password.length < PASSWORD_MIN) clientErrors.password = FIELD_MESSAGES.password!

  const serverErrors = Object.fromEntries(
    Object.keys(fieldErrorsOf(register.error)).map((field) => [field, FIELD_MESSAGES[field] ?? '값을 확인해 주세요.']),
  )
  const errors = touched ? { ...serverErrors, ...clientErrors } : serverErrors
  const emailTaken = register.error instanceof ApiError && register.error.code === 'email_taken'
  const formError = register.isError && Object.keys(serverErrors).length === 0 ? messageOf(register.error) : null

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (Object.keys(clientErrors).length > 0 || !agree) return
    register.mutate({ name: name.trim(), email: email.trim(), password, job_type: jobType, agree_terms: agree })
  }

  const loginHref = searchParams.get('next') ? `/login?${searchParams.toString()}` : '/login'

  return (
    <form className="auth-form" onSubmit={onSubmit} noValidate>
      <div className="auth-form-head">
        <p className="auth-eyebrow">나만의 워크스페이스 만들기</p>
        <h1>회원가입</h1>
        <p>계약과 프로젝트 관리를 시작하세요.</p>
      </div>

      <TextField
        label="이름"
        autoComplete="name"
        placeholder="이름을 입력하세요"
        value={name}
        onChange={(e) => setName(e.target.value)}
        maxLength={50}
        error={errors.name}
      />
      <TextField
        label="이메일"
        type="email"
        inputMode="email"
        autoComplete="email"
        placeholder="이메일을 입력하세요"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        error={errors.email}
      />
      <TextField
        label="비밀번호"
        type="password"
        autoComplete="new-password"
        placeholder={`${PASSWORD_MIN}자 이상 입력하세요`}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        maxLength={128}
        error={errors.password}
      />
      <SelectField
        label="기본 직업군"
        options={JOB_OPTIONS}
        value={jobType}
        onChange={(e) => setJobType(e.target.value as JobType)}
        error={errors.job_type}
        hint="계약서를 검토할 때 기본으로 적용할 직업군이에요. 나중에 바꿀 수 있어요."
      />

      <fieldset className="consent-group">
        <legend>필수 동의</legend>
        <label className="checkbox">
          <input name="agree_terms" type="checkbox" required checked={agreeTerms} onChange={(e) => setAgreeTerms(e.target.checked)} aria-invalid={touched && !agreeTerms || undefined} />
          [필수] 이용약관 동의
        </label>
        <label className="checkbox">
          <input name="agree_privacy" type="checkbox" required checked={agreePrivacy} onChange={(e) => setAgreePrivacy(e.target.checked)} aria-invalid={touched && !agreePrivacy || undefined} />
          [필수] 개인정보 수집·이용 동의
        </label>
        {touched && !agree && <p className="field-error" role="alert">필수 항목 두 가지에 각각 동의해 주세요.</p>}
      </fieldset>
      <fieldset className="consent-group">
        <legend>선택 동의</legend>
        <p className="field-hint">현재 요청하는 선택 동의는 없어요. 광고성 정보 수신 동의 없이 가입할 수 있어요.</p>
      </fieldset>

      {formError && (
        <div className="alert alert-error" role="alert">
          {formError}
          {emailTaken && (
            <>
              {' '}
              <Link to={loginHref} className="link-strong">
                로그인하기
              </Link>
            </>
          )}
        </div>
      )}

      <button type="submit" className="btn btn-primary btn-block" disabled={register.isPending}>
        {register.isPending ? '만드는 중…' : '계정 만들기'}
      </button>

      <p className="auth-switch">
        이미 계정이 있으신가요?
        <Link to={loginHref} className="link-strong">
          로그인
        </Link>
      </p>
    </form>
  )
}
