import { useState, type FormEvent } from 'react'
import { useLocation, useOutletContext } from 'react-router'

import { useLlmStatus, useTestLlm } from '../api/analysis'
import {
  useActivateLlmModel,
  useAddLlmModel,
  useChangePassword,
  useDeleteLlmModel,
  useUpdateMe,
  type JobType,
  type LlmMode,
  type User,
  type UserUpdate,
} from '../api/auth'
import { ApiError, fieldErrorsOf } from '../api/client'
import { messageOf } from '../api/messages'
import { SelectField, TextField } from '../components/Field'
import { avatarInitial, JOB_TYPE_LABELS, LLM_MODE_LABELS } from '../lib/format'

type FormState = {
  name: string
  job_type: JobType
  default_llm_mode: LlmMode
  issuer_name: string
  issuer_display_name: string
  issuer_contact: string
  bank_name: string
  bank_account: string
}

const OPTIONAL_TEXT_FIELDS = [
  'issuer_name',
  'issuer_display_name',
  'issuer_contact',
  'bank_name',
  'bank_account',
] as const

const SECTIONS = [
  { id: 'profile', label: '프로필' },
  { id: 'issuer', label: '문서 발행 정보' },
  { id: 'ai', label: 'AI 설정' },
  { id: 'security', label: '보안' },
] as const

const JOB_OPTIONS = Object.entries(JOB_TYPE_LABELS).map(([value, label]) => ({ value, label }))

const MODE_TYPE_OPTIONS = [
  { value: 'commercial', label: '상용 API (외부 전송 시 개인정보 마스킹·동의)' },
  { value: 'local', label: '로컬 LLM (내 추론 서버 · 마스킹 없음)' },
] as const

/** 실행 방식 옵션. 사용할 수 없는 방식은 이름에 상태를 붙여 보여준다. */
function llmOptions(status: ReturnType<typeof useLlmStatus>['data']): Array<{ value: LlmMode; label: string }> {
  const commercial = status?.commercial
  const local = status?.local
  const commercialLabel = LLM_MODE_LABELS.commercial + (commercial && !commercial.available ? ' (미등록)' : '')
  const localLabel = LLM_MODE_LABELS.local + (local && !local.available ? ' (미등록)' : '')
  return [
    { value: 'ask' as const, label: LLM_MODE_LABELS.ask },
    { value: 'commercial' as const, label: commercialLabel },
    { value: 'local' as const, label: localLabel },
  ]
}

function toForm(user: User): FormState {
  return {
    name: user.name,
    job_type: user.job_type,
    default_llm_mode: user.default_llm_mode,
    issuer_name: user.issuer_name ?? '',
    issuer_display_name: user.issuer_display_name ?? '',
    issuer_contact: user.issuer_contact ?? '',
    bank_name: user.bank_name ?? '',
    bank_account: user.bank_account ?? '',
  }
}

/** 바뀐 필드만 보낸다. 빈 문자열은 선택 항목이면 null(비움)로 보낸다. */
function diff(form: FormState, saved: FormState): UserUpdate {
  const changes: UserUpdate = {}
  if (form.name.trim() !== saved.name) changes.name = form.name.trim()
  if (form.job_type !== saved.job_type) changes.job_type = form.job_type
  if (form.default_llm_mode !== saved.default_llm_mode) changes.default_llm_mode = form.default_llm_mode
  for (const key of OPTIONAL_TEXT_FIELDS) {
    const value = form[key].trim()
    if (value !== saved[key]) changes[key] = value === '' ? null : value
  }
  return changes
}

/** 12 내 정보와 설정 */
export function SettingsPage() {
  const user = useOutletContext<User>()
  const location = useLocation()
  const update = useUpdateMe()
  const llm = useLlmStatus()

  const initialTab = location.hash ? location.hash.replace('#', '') : 'profile'
  const [saved, setSaved] = useState(() => toForm(user))
  const [form, setForm] = useState(saved)
  const [activeSection, setActiveSection] = useState<string>(
    SECTIONS.some((s) => s.id === initialTab) ? initialTab : 'profile',
  )
  const [justSaved, setJustSaved] = useState(false)

  const changes = diff(form, saved)
  const dirty = Object.keys(changes).length > 0
  const nameMissing = form.name.trim() === ''
  const serverFieldErrors = fieldErrorsOf(update.error)

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((f) => ({ ...f, [key]: value }))
    setJustSaved(false)
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (!dirty || nameMissing) return
    update.mutate(changes, {
      onSuccess: (next) => {
        const fresh = toForm(next)
        setSaved(fresh)
        setForm(fresh)
        setJustSaved(true)
      },
    })
  }

  return (
    <div className="settings-page">
      <form onSubmit={onSubmit} noValidate>
        <div className="page-head">
          <div>
            <p className="page-eyebrow">나의 워크스페이스</p>
            <h1 className="page-title">내 정보와 설정</h1>
            <p className="page-desc">프로필, 문서 발행 정보, AI 모델을 관리하세요.</p>
          </div>
          <div className="save-bar">
            <span className="save-status" role="status">
              {update.isError ? '' : justSaved ? '저장했어요.' : dirty ? '저장하지 않은 변경사항이 있어요.' : ''}
            </span>
            <button type="submit" className="btn btn-primary" disabled={!dirty || nameMissing || update.isPending}>
              {update.isPending ? '저장 중…' : '변경사항 저장'}
            </button>
          </div>
        </div>

        <nav className="settings-tabs" aria-label="설정 섹션">
          {SECTIONS.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={activeSection === s.id ? 'active' : undefined}
              onClick={() => setActiveSection(s.id)}
            >
              {s.label}
            </a>
          ))}
        </nav>

        {update.isError && (
          <div className="alert alert-error" role="alert" style={{ marginBottom: 24 }}>
            {messageOf(update.error)}
          </div>
        )}

        <div className="grid-2">
          <section id="profile" className="card settings-section" aria-labelledby="profile-title">
            <h2 id="profile-title" className="card-title">
              프로필
            </h2>
            <div className="profile-head">
              <span className="avatar avatar-lg">{avatarInitial(saved.name)}</span>
              <div>
                <strong>{saved.name}</strong>
                <span>프리랜서 {JOB_TYPE_LABELS[saved.job_type]}</span>
              </div>
            </div>
            <div className="form-grid">
              <TextField
                label="이름"
                autoComplete="name"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                maxLength={50}
                error={nameMissing ? '이름을 입력해 주세요.' : serverFieldErrors.name}
              />
              <SelectField
                label="기본 직업군"
                options={JOB_OPTIONS}
                value={form.job_type}
                onChange={(e) => set('job_type', e.target.value as JobType)}
              />
              <TextField
                label="이메일"
                type="email"
                value={user.email}
                readOnly
                fieldClassName="span-2"
                hint="로그인에 쓰는 이메일은 바꿀 수 없어요."
              />
            </div>
          </section>

          <section id="issuer" className="card settings-section" aria-labelledby="issuer-title">
            <h2 id="issuer-title" className="card-title">
              문서 발행 정보
            </h2>
            <div className="form-grid">
              <TextField
                label="발행자명"
                value={form.issuer_name}
                onChange={(e) => set('issuer_name', e.target.value)}
                maxLength={100}
              />
              <TextField
                label="표시 이름 또는 상호"
                value={form.issuer_display_name}
                onChange={(e) => set('issuer_display_name', e.target.value)}
                maxLength={100}
              />
              <TextField
                label="문서에 표시할 연락처"
                value={form.issuer_contact}
                onChange={(e) => set('issuer_contact', e.target.value)}
                maxLength={200}
                fieldClassName="span-2"
              />
              <TextField
                label="입금 은행"
                value={form.bank_name}
                onChange={(e) => set('bank_name', e.target.value)}
                maxLength={50}
              />
              <TextField
                label="계좌 정보"
                autoComplete="off"
                value={form.bank_account}
                onChange={(e) => set('bank_account', e.target.value)}
                maxLength={100}
              />
            </div>
            <p className="field-hint" style={{ margin: '16px 0 0' }}>
              발행된 인보이스에는 발행 시점의 정보가 유지됩니다.
            </p>
          </section>
        </div>

        <section
          id="ai"
          className="card settings-section"
          aria-labelledby="ai-title"
          style={{ marginTop: 24 }}
        >
          <div className="between" style={{ marginBottom: 16 }}>
            <h2 id="ai-title" className="card-title" style={{ margin: 0 }}>
              AI 설정
            </h2>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <span className={llm.data?.commercial?.available ? 'badge badge-green' : 'badge badge-gray'}>
                상용: {llm.data?.commercial?.available ? `${llm.data.commercial.model ?? '연결됨'}` : '미등록'}
              </span>
              <span className={llm.data?.local?.available ? 'badge badge-green' : 'badge badge-gray'}>
                로컬: {llm.data?.local?.available ? `${llm.data.local.model ?? '연결됨'}` : '미등록'}
              </span>
            </div>
          </div>

          <div className="form-grid">
            <TextField
              label="기본 검토 직업군"
              value={JOB_TYPE_LABELS[form.job_type]}
              readOnly
              hint="프로필의 기본 직업군을 따라요."
            />
            <SelectField
              label="기본 실행 방식"
              options={llmOptions(llm.data)}
              value={form.default_llm_mode}
              onChange={(e) => set('default_llm_mode', e.target.value as LlmMode)}
            />
          </div>
          <p className="field-hint" style={{ margin: '12px 0 0' }}>
            계약서 분석 화면에서 이 방식이 먼저 선택돼요. &quot;매번 선택&quot;이면 분석할 때마다 고르세요.
          </p>
        </section>
      </form>

      <AiModelManagerSection user={user} />

      <SecuritySection />
    </div>
  )
}

/** AI 모델 추가 및 목록 관리 */
function AiModelManagerSection({ user }: { user: User }) {
  const addModel = useAddLlmModel()
  const activateModel = useActivateLlmModel()
  const deleteModel = useDeleteLlmModel()
  const testLlm = useTestLlm()

  const [mode, setMode] = useState<'commercial' | 'local'>('commercial')
  const [apiBase, setApiBase] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [modelName, setModelName] = useState('')

  const canAdd = modelName.trim() !== '' && !addModel.isPending

  const onTest = () => {
    if (!modelName.trim()) return
    testLlm.mutate({
      mode,
      model: modelName.trim(),
      api_base: apiBase.trim() || undefined,
      api_key: apiKey.trim() || undefined,
    })
  }

  const onAdd = (e: FormEvent) => {
    e.preventDefault()
    if (!canAdd) return
    addModel.mutate(
      {
        mode,
        model: modelName.trim(),
        api_base: apiBase.trim() || null,
        api_key: apiKey.trim() || null,
      },
      {
        onSuccess: () => {
          setModelName('')
          setApiKey('')
          setApiBase('')
          testLlm.reset()
        },
      },
    )
  }

  const models = user.llm_models ?? []

  return (
    <section className="card settings-section" aria-labelledby="ai-models-title" style={{ marginTop: 24 }}>
      <h2 id="ai-models-title" className="card-title">
        모델 추가 및 관리
      </h2>
      <p className="field-hint" style={{ marginTop: 0, marginBottom: 16 }}>
        Base URL, API Key, Model 이름을 직접 입력해 추가하세요. API 통신 규격(OpenAI 호환, Gemini, Claude, Ollama 등)은 LiteLLM이 자동으로 판별합니다.
      </p>

      <form onSubmit={onAdd} className="form-grid" noValidate style={{ marginBottom: 24 }}>
        <SelectField
          label="실행 구분"
          options={[...MODE_TYPE_OPTIONS]}
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as 'commercial' | 'local')
            testLlm.reset()
          }}
        />
        <TextField
          label="Model (모델명)"
          placeholder="예: gpt-4o, gemini-2.5-flash, qwen2.5:7b"
          value={modelName}
          onChange={(e) => {
            setModelName(e.target.value)
            testLlm.reset()
          }}
          maxLength={200}
        />
        <TextField
          label="Base URL (엔드포인트 주소)"
          placeholder={
            mode === 'local'
              ? '예: http://host.docker.internal:11434 또는 http://localhost:8000/v1'
              : '예: https://api.openai.com/v1 (공식 Gemini·OpenAI·Claude는 비워도 자동 연결)'
          }
          value={apiBase}
          onChange={(e) => {
            setApiBase(e.target.value)
            testLlm.reset()
          }}
          maxLength={500}
        />
        <TextField
          label="API Key"
          type="password"
          autoComplete="new-password"
          placeholder={mode === 'local' ? '필요한 경우에만 입력 (없으면 비워 두세요)' : 'API Key 입력 (예: sk-..., AIza...)'}
          value={apiKey}
          onChange={(e) => {
            setApiKey(e.target.value)
            testLlm.reset()
          }}
          maxLength={500}
        />

        <div className="span-2 between" style={{ marginTop: 4 }}>
          <div style={{ flex: 1 }}>
            {testLlm.isSuccess && (
              <div className="alert alert-success" role="status">
                {testLlm.data.message}
              </div>
            )}
            {testLlm.isError && (
              <div className="alert alert-error" role="alert">
                {messageOf(testLlm.error)}
              </div>
            )}
            {addModel.isError && (
              <div className="alert alert-error" role="alert">
                {messageOf(addModel.error)}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!modelName.trim() || testLlm.isPending}
              onClick={onTest}
            >
              {testLlm.isPending ? '테스트 중…' : '연결 테스트'}
            </button>
            <button type="submit" className="btn btn-primary" disabled={!canAdd}>
              {addModel.isPending ? '추가 중…' : '+ 모델 추가'}
            </button>
          </div>
        </div>
      </form>

      <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 20 }}>
        <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>
          등록된 모델 ({models.length})
        </h3>
        {models.length === 0 ? (
          <p className="muted" style={{ margin: 0 }}>
            아직 등록된 모델이 없어요. 위에서 사용할 모델을 추가해 주세요.
          </p>
        ) : (
          <ul className="row-list" style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {models.map((item) => (
              <li
                key={item.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  padding: '14px 16px',
                  border: item.is_active ? '1px solid var(--color-primary)' : '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-md)',
                  background: item.is_active ? 'var(--color-primary-soft)' : 'var(--color-surface)',
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span className={item.mode === 'local' ? 'badge badge-amber' : 'badge badge-gray'}>
                      {item.mode === 'local' ? '로컬 LLM' : '상용 API'}
                    </span>
                    <strong style={{ fontSize: 15 }}>{item.model}</strong>
                    {item.is_active && <span className="badge badge-green">사용 중</span>}
                  </div>
                  <span className="muted small">
                    Base URL: {item.api_base ?? '(공식 기본 엔드포인트)'} · API Key: {item.has_api_key ? '저장됨 (••••)' : '없음'}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {!item.is_active && (
                    <button
                      type="button"
                      className="btn btn-secondary"
                      style={{ minHeight: 34, padding: '0 12px', fontSize: 13 }}
                      disabled={activateModel.isPending}
                      onClick={() => activateModel.mutate(item.id)}
                    >
                      사용하기
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn btn-danger-text small"
                    disabled={deleteModel.isPending}
                    onClick={() => deleteModel.mutate(item.id)}
                  >
                    삭제
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="notice" style={{ marginTop: 20 }}>
        <p>상용 모델 전송은 분석할 때마다 확인합니다. API 키는 서버에만 보관되며 화면 응답이나 로그에 노출되지 않습니다.</p>
      </div>
    </section>
  )
}

/** 설정의 "보안": 비밀번호 변경. 바꾸면 다른 기기의 세션은 로그아웃된다. */
function SecuritySection() {
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [done, setDone] = useState(false)

  const tooShort = next !== '' && next.length < 8
  const mismatch = confirmPw !== '' && next !== confirmPw
  const code = change.error instanceof ApiError ? change.error.code : null
  const canSubmit = current !== '' && !tooShort && !mismatch && next === confirmPw && !change.isPending

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setDone(true)
          setCurrent('')
          setNext('')
          setConfirmPw('')
        },
      },
    )
  }

  return (
    <section id="security" className="card settings-section" aria-labelledby="security-title" style={{ marginTop: 24 }}>
      <h2 id="security-title" className="card-title">
        보안
      </h2>
      <form onSubmit={submit} className="form-grid" noValidate>
        <TextField
          label="현재 비밀번호"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          error={code === 'wrong_password' ? '현재 비밀번호가 올바르지 않아요.' : undefined}
        />
        <TextField
          label="새 비밀번호"
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => {
            setNext(e.target.value)
            setDone(false)
          }}
          error={tooShort ? '8자 이상으로 입력해 주세요.' : code === 'same_password' ? '지금 쓰는 비밀번호와 같아요.' : undefined}
        />
        <TextField
          label="새 비밀번호 확인"
          type="password"
          autoComplete="new-password"
          value={confirmPw}
          onChange={(e) => setConfirmPw(e.target.value)}
          error={mismatch ? '새 비밀번호와 같지 않아요.' : undefined}
        />
        <div className="save-bar" style={{ alignSelf: 'end' }}>
          <span className="save-status" role="status">
            {change.isError && code !== 'wrong_password' && code !== 'same_password'
              ? messageOf(change.error)
              : done
                ? '비밀번호를 바꿨어요. 다른 기기에서는 다시 로그인해야 해요.'
                : ''}
          </span>
          <button type="submit" className="btn btn-secondary" disabled={!canSubmit}>
            {change.isPending ? '변경 중…' : '비밀번호 변경'}
          </button>
        </div>
      </form>
      <p className="field-hint" style={{ margin: '16px 0 0' }}>
        비밀번호를 바꾸면 다른 브라우저·기기에서는 다시 로그인해야 해요.
      </p>
    </section>
  )
}
