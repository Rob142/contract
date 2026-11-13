import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { useAnalysis, useLlmStatus, useRequestAnalysis } from '../api/analysis'
import { useMe } from '../api/auth'
import type { ContractDetail } from '../api/contracts'
import { messageOf } from '../api/messages'
import { JobTypeSelect } from './JobTypeSelect'

const FAILURE_LABELS: Record<string, string> = {
  llm_blocked: '모델이 이 문서의 분석을 거절했어요.',
  llm_truncated: '분석 결과가 너무 길어 중간에 끊겼어요. 다시 시도해 주세요.',
  llm_invalid_json: '모델 응답 형식이 올바르지 않았어요. 다시 시도해 주세요.',
  llm_invalid_output: '모델 응답 형식이 올바르지 않았어요. 다시 시도해 주세요.',
  llm_unavailable: '모델 서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.',
  llm_auth_failed: 'API 키가 거절됐어요. 설정의 AI 탭에서 API 키를 확인해 주세요.',
  llm_not_configured: '상용 모델 API 키가 설정되지 않았어요. 설정의 AI 탭에서 입력해 주세요.',
  local_llm_not_configured: '로컬 LLM이 설정되지 않았어요. 설정의 AI 탭에서 연결해 주세요.',
  timeout: '분석 시간이 너무 오래 걸려 멈췄어요.',
}

const PROVIDER_LABELS: Record<string, string> = {
  gemini: 'Google Gemini',
  openai: 'OpenAI',
  anthropic: 'Anthropic Claude',
  ollama: 'Ollama',
  ollama_chat: 'Ollama',
  litellm: 'LiteLLM',
}

function formatModelLabel(provider?: string | null, model?: string | null): string {
  if (!provider && !model) return ''
  if (provider === 'fake') return '시연용 가짜 모델 (외부 전송 없음)'
  const pLabel = provider ? (PROVIDER_LABELS[provider] ?? provider) : ''
  return [pLabel, model].filter(Boolean).join(' · ')
}

/** 05의 "분석 설정": 직업군과 실행 방식을 고르고, 상용 모델이면 외부 전송에 동의해야 시작한다.
 * 설정에서 고른 "기본 실행 방식"으로 미리 선택된다. "매번 선택"이면 사용자가 매번 고른다. */
export function AnalysisCard({ contract }: { contract: ContractDetail }) {
  const llm = useLlmStatus()
  const me = useMe()
  const view = useAnalysis(contract.id)
  const request = useRequestAnalysis(contract.id)
  // null = 아직 고르지 않음 (설정이 "매번 선택"이거나 로딩 중)
  const [mode, setMode] = useState<'commercial' | 'local' | null>(null)
  const [consent, setConsent] = useState(false)
  const [prefilled, setPrefilled] = useState(false)

  const defaultMode = me.data?.default_llm_mode
  const localReady = llm.data?.local?.available === true
  useEffect(() => {
    // 설정값을 한 번만 반영한다. 로컬이 준비됐는지는 LLM 상태를 읽은 뒤 판단한다.
    if (prefilled || !defaultMode) return
    if (defaultMode === 'commercial') {
      setMode('commercial')
      setPrefilled(true)
    } else if (defaultMode === 'local' && (llm.isPending || localReady)) {
      if (!llm.isPending) {
        setMode(localReady ? 'local' : 'commercial')
        setPrefilled(true)
      }
    } else if (defaultMode === 'ask') {
      setPrefilled(true)
    }
  }, [prefilled, defaultMode, llm.isPending, localReady])

  const latest = view.data?.latest_job
  const running = latest?.status === 'queued' || latest?.status === 'running'
  const done = view.data?.analysis
  const commercial = llm.data?.commercial
  const local = llm.data?.local
  const modeAvailable = mode === 'commercial' ? commercial?.available : mode === 'local' ? local?.available : false
  const isFake = commercial?.provider === 'fake'
  const canStart = mode !== null && modeAvailable && (mode === 'local' || consent) && !running && !request.isPending

  const start = (force: boolean) =>
    request.mutate({
      llm_mode: mode === 'local' ? 'local' : 'commercial',
      job_type: contract.job_type,
      consent_external: mode === 'commercial' && consent,
      force,
    })

  return (
    <section className="card" aria-labelledby="analysis-title">
      <div className="card-head">
        <h2 id="analysis-title" className="card-title">
          ② AI 계약 분석
        </h2>
        {done && <span className="badge badge-green">분석 완료</span>}
      </div>

      {running ? (
        <div className="analysis-running" role="status">
          <span className="spinner spinner-sm" aria-hidden="true" />
          <div>
            <strong>{latest?.stage === 'validating' ? '원문 근거를 대조하고 있어요' : '계약서를 분석하고 있어요'}</strong>
            <p className="muted small" style={{ margin: 0 }}>
              다른 화면으로 이동해도 계속 진행돼요.
            </p>
          </div>
        </div>
      ) : (
        <div className="stack-sm">
          <JobTypeSelect contract={contract} label="검토 직업군" />
          <div className="mode-options" role="radiogroup" aria-label="실행 방식">
            <button
              type="button"
              role="radio"
              aria-checked={mode === 'commercial'}
              className={mode === 'commercial' ? 'mode-option is-selected' : 'mode-option'}
              onClick={() => setMode('commercial')}
            >
              <strong>상용 LLM API</strong>
              <span className="muted small">
                {formatModelLabel(commercial?.provider, commercial?.model) || '상용 추론 모델'}
              </span>
              {commercial && !commercial.available && <span className="field-error small">API 키 미설정</span>}
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={mode === 'local'}
              className={mode === 'local' ? 'mode-option is-selected' : 'mode-option'}
              onClick={() => setMode('local')}
            >
              <strong>로컬 LLM</strong>
              <span className="muted small">
                {local?.available ? formatModelLabel(local.provider, local.model) : '로컬 추론 서버 사용'}
              </span>
              {local && !local.available && <span className="muted small">아직 연결 전</span>}
            </button>
          </div>
          {mode === null && (
            <p className="field-hint" style={{ margin: 0 }}>
              실행 방식을 골라 주세요. <Link to="/settings#ai" className="link-strong">설정 → AI</Link>에서 모델과 기본값을 바꿀 수 있어요.
            </p>
          )}

          {mode === 'commercial' ? (
            <>
              <div className="notice">
                <p>
                  상용 API를 선택하면 확인한 계약서 텍스트가 {isFake ? '분석 모델' : (PROVIDER_LABELS[commercial?.provider ?? ''] ?? commercial?.model ?? '외부 모델')}로 전송돼요. 이메일·전화번호·계좌번호는 가려서 보내요.
                </p>
              </div>
              <label className="checkbox">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                전송 내용을 확인하고 분석에 동의합니다
              </label>
            </>
          ) : (
            <div className="notice">
              <p>
                로컬 LLM은 외부 API로 자동 전환하지 않아요.{' '}
                {local?.available ? (
                  <>설정한 로컬 추론 서버({local.model})로 분석해요.</>
                ) : (
                  <>
                    <Link to="/settings#ai" className="link-strong">
                      설정 → AI
                    </Link>
                    에서 로컬 추론 서버를 연결하면 사용할 수 있어요.
                  </>
                )}
              </p>
            </div>
          )}

          {latest?.status === 'failed' && (
            <div className="alert alert-error" role="alert">
              지난 분석이 실패했어요. {FAILURE_LABELS[latest.error_code ?? ''] ?? '다시 시도해 주세요.'}
            </div>
          )}
          {request.isError && (
            <div className="alert alert-error" role="alert">
              {messageOf(request.error)}
            </div>
          )}

          <button type="button" className="btn btn-primary btn-block" disabled={!canStart} onClick={() => start(Boolean(done))}>
            {done ? '다시 분석' : '계약 분석 시작'}
          </button>
        </div>
      )}

      {done && !running && (
        <Link to={`/contracts/${contract.id}/analysis`} className="btn btn-secondary btn-block" style={{ marginTop: 10 }}>
          분석 결과 보기 · 주의 {done.counts.caution} · 확인 필요 {done.counts.needs_check}
        </Link>
      )}
    </section>
  )
}
