import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'

import { useLogin } from '../api/auth'
import { messageOf } from '../api/messages'
import { TextField } from '../components/Field'

/** 01 로그인. 성공하면 GuestOnly가 ?next 위치로 보낸다. */
export function LoginPage() {
  const login = useLogin()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    login.mutate({ email: email.trim(), password, remember })
  }

  const signupHref = searchParams.get('next') ? `/signup?${searchParams.toString()}` : '/signup'

  return (
    <form className="auth-form" onSubmit={onSubmit} noValidate>
      <div className="auth-form-head">
        <p className="auth-eyebrow">다시 만나 반가워요</p>
        <h1>로그인</h1>
        <p>진행 중인 프로젝트를 이어서 관리하세요.</p>
      </div>

      <TextField
        label="이메일"
        type="email"
        inputMode="email"
        autoComplete="username"
        placeholder="이메일을 입력하세요"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      <TextField
        label="비밀번호"
        type="password"
        autoComplete="current-password"
        placeholder="비밀번호를 입력하세요"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />

      <label className="checkbox">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
        로그인 상태 유지
      </label>

      {login.isError && (
        <div className="alert alert-error" role="alert">
          {messageOf(login.error)}
        </div>
      )}

      <button
        type="submit"
        className="btn btn-primary btn-block"
        disabled={login.isPending || !email.trim() || !password}
      >
        {login.isPending ? '로그인 중…' : '로그인'}
      </button>

      <p className="auth-switch">
        아직 계정이 없으신가요?
        <Link to={signupHref} className="link-strong">
          회원가입
        </Link>
      </p>
    </form>
  )
}
