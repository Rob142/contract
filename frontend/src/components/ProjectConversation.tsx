import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { cs, useCS, type ClientProject } from '../api/clientService'
import { ActionForm, Area, ErrorNotice } from './ClientServiceUI'

type Chat = {
  id: string
  topic: string
  state: string
  requester_name: string
  requested_by: string
  expires_at: string | null
  can_respond: boolean
  created_at: string
}
type Message = {
  id: string
  session_id: string | null
  actor_id: string
  actor_name: string
  actor_side: string
  body: string
  created_at: string
}
type Conversation = {
  current: Chat | null
  sessions: Chat[]
  messages: Message[]
  can_write: boolean
}
const CHAT_STATES: Record<string, string> = {
  pending: '수락 대기',
  active: '실시간 대화 중',
  closed: '종료',
  declined: '거절됨',
  expired: '만료됨',
}
export function ProjectConversation({ project }: { project: ClientProject }) {
  const path = `/projects/${project.id}/conversation`
  const conversation = useCS<Conversation>(path)
  const qc = useQueryClient()
  const [connection, setConnection] = useState('연결 중')
  const [accessEnded, setAccessEnded] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [requestReset, setRequestReset] = useState(0)
  const [chatReset, setChatReset] = useState(0)
  useEffect(() => {
    const source = new EventSource(`/api/v1/client-service${path}/events`)
    source.onopen = () => setConnection('실시간 연결됨')
    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as Conversation
        qc.setQueryData(['client-service', path], data)
        setConnection('실시간 연결됨')
      } catch {
        setConnection('메시지 갱신 오류 · 재연결 필요')
      }
    }
    source.onerror = () => {
      setConnection('연결 끊김 · 재연결 중')
      void cs<Conversation>('GET', path).catch((err) => {
        setError(err)
      })
    }
    const end = () => {
      source.close()
      setAccessEnded(true)
      qc.removeQueries({ queryKey: ['client-service', path] })
    }
    source.addEventListener('access-ended', end)
    return () => {
      source.removeEventListener('access-ended', end)
      source.close()
    }
  }, [path, qc])
  if (accessEnded)
    return (
      <p className="alert alert-error" role="alert">
        로그인이 만료되었거나 프로젝트 접근 권한이 해제되었습니다. 다시
        로그인하거나 담당자에게 확인하세요.
      </p>
    )
  if (conversation.isPending)
    return <p role="status">대화와 요청사항을 불러오는 중…</p>
  if (conversation.error) return <ErrorNotice error={conversation.error} />
  const data = conversation.data
  if (!data) return null
  const chat = data.current
  const requests = data.messages.filter((m) => !m.session_id)
  const inSession = data.messages.filter((m) => m.session_id === chat?.id)
  const send = async (body: string, session_id: string | null) => {
    setError(null)
    const value = await cs<Conversation>(
      'POST',
      `/projects/${project.id}/messages`,
      { body, session_id },
    )
    qc.setQueryData(['client-service', path], value)
  }
  return (
    <div className="cs-conversation">
      <p className="cs-note">
        평소 메시지는 ‘요청사항’으로 남습니다. 한쪽이 대화를 요청하고 반대쪽이
        수락해야 실시간 채팅이 열립니다. 메시지·채팅만으로 수정 횟수나 계약
        조건이 바뀌지 않습니다.
      </p>
      <ErrorNotice error={error} />
      <section className="cs-card">
        <div className="cs-section-head">
          <h3>실시간 대화</h3>
          <span className="cs-connection" role="status">
            {connection}
          </span>
        </div>
        {!chat && (
          <>
            <p>
              현재 열린 실시간 채팅이 없습니다. 요청사항은 아래에서 언제든 남길
              수 있습니다.
            </p>
            {data.can_write && (
              <ActionForm
                title="상대방에게 실시간 대화 요청"
                label="실시간 대화 요청 보내기"
                onSubmit={async (form) => {
                  const result = await cs<Conversation>(
                    'POST',
                    `/projects/${project.id}/chat-sessions`,
                    { body: String(form.get('topic') ?? '').trim() },
                  )
                  qc.setQueryData(['client-service', path], result)
                }}
              >
                <Area label="대화 주제·가능한 시간" name="topic" required />
                <p className="field-hint">
                  요청은 24시간 후 만료됩니다. 상대방이 수락하기 전에는 채팅을
                  보낼 수 없습니다.
                </p>
              </ActionForm>
            )}
          </>
        )}
        {chat?.state === 'pending' && (
          <div className="cs-chat-invitation">
            <span className="cs-state">수락 대기</span>
            <h4>{chat.requester_name} 님이 실시간 대화를 요청했습니다</h4>
            <p className="cs-pre">{chat.topic}</p>
            <p className="field-hint">
              {chat.expires_at &&
                `${new Date(chat.expires_at).toLocaleString('ko-KR')}까지 수락 가능`}
            </p>
            {data.can_write && (
              <div className="cs-actions">
                {chat.can_respond ? (
                  <>
                    <ActionForm
                      title="대화 요청 수락"
                      label="수락하고 채팅 시작"
                      onSubmit={() =>
                        cs(
                          'POST',
                          `/projects/${project.id}/chat-sessions/${chat.id}`,
                          { action: 'accept' },
                        )
                      }
                    >
                      <small>
                        담당 프리랜서와 프로젝트의 클라이언트 참여자가
                        대화합니다.
                      </small>
                    </ActionForm>
                    <ActionForm
                      title="대화 요청 거절"
                      label="이번 요청 거절"
                      onSubmit={() =>
                        cs(
                          'POST',
                          `/projects/${project.id}/chat-sessions/${chat.id}`,
                          { action: 'decline' },
                        )
                      }
                    >
                      <small>요청사항으로 협의를 이어갈 수 있습니다.</small>
                    </ActionForm>
                  </>
                ) : (
                  <ActionForm
                    title="대화 요청 취소"
                    label="요청 취소"
                    onSubmit={() =>
                      cs(
                        'POST',
                        `/projects/${project.id}/chat-sessions/${chat.id}`,
                        { action: 'close' },
                      )
                    }
                  >
                    <small>상대방의 수락을 기다리는 중입니다.</small>
                  </ActionForm>
                )}
              </div>
            )}
          </div>
        )}
        {chat?.state === 'active' && (
          <>
            <div className="cs-chat-banner">
              <span className="cs-state cs-state-approved">실시간 대화 중</span>
              <strong>{chat.topic}</strong>
              {chat.expires_at && (
                <small>
                  {new Date(chat.expires_at).toLocaleTimeString('ko-KR')} 자동
                  종료
                </small>
              )}
            </div>
            <MessageList messages={inSession} live />
            {data.can_write && (
              <ActionForm
                key={`chat-${chatReset}`}
                title="채팅 메시지"
                label="채팅 전송"
                onSubmit={async (form) => {
                  await send(String(form.get('body') ?? '').trim(), chat.id)
                  setChatReset((n) => n + 1)
                }}
              >
                <Area label="채팅 내용" name="body" required />
                <small>
                  Enter는 줄바꿈입니다. 전송 버튼으로 보내세요. 연결이 끊기면
                  전송 결과를 확인하고 다시 시도하세요.
                </small>
              </ActionForm>
            )}
            {data.can_write && (
              <ActionForm
                title="실시간 대화 종료"
                label="대화 종료"
                onSubmit={() =>
                  cs(
                    'POST',
                    `/projects/${project.id}/chat-sessions/${chat.id}`,
                    { action: 'close' },
                  )
                }
              >
                <small>
                  어느 쪽이든 종료할 수 있습니다. 기록은 남고 이후 메시지는
                  요청사항으로 작성합니다.
                </small>
              </ActionForm>
            )}
          </>
        )}
        <details className="cs-chat-history">
          <summary>
            이전 실시간 대화 기록 (
            {
              data.sessions.filter(
                (s) => !['active', 'pending'].includes(s.state),
              ).length
            }
            )
          </summary>
          {data.sessions
            .filter((s) => !['active', 'pending'].includes(s.state))
            .reverse()
            .map((s) => (
              <section className="cs-quote" key={s.id}>
                <h4>
                  {s.topic} · {CHAT_STATES[s.state]}
                </h4>
                <p>
                  {s.requester_name} 요청 ·{' '}
                  {new Date(s.created_at).toLocaleString('ko-KR')}
                </p>
                <MessageList
                  messages={data.messages.filter((m) => m.session_id === s.id)}
                />
              </section>
            ))}
        </details>
      </section>
      <section className="cs-card">
        <h3>요청사항</h3>
        <p>
          채팅 참여 여부와 관계없이 남겨 둘 업무 요청·자료 안내·질문입니다. 공식
          수정 요청은 ‘결과물·검수’에서 별도로 취합해 제출하세요.
        </p>
        <MessageList messages={requests} />
        {data.can_write && (
          <ActionForm
            key={`request-${requestReset}`}
            title="요청사항 남기기"
            label="요청사항 등록"
            onSubmit={async (form) => {
              await send(String(form.get('body') ?? '').trim(), null)
              setRequestReset((n) => n + 1)
            }}
          >
            <Area label="요청사항·자료 전달 안내" name="body" required />
          </ActionForm>
        )}
      </section>
      <section className="cs-card">
        <h3>전달된 자료</h3>
        {project.deliveries
          .filter((d) => d.current)
          .flatMap((d) =>
            d.payload.attachments.map((a) => (
              <p key={`${d.id}-${a.id}`}>
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noopener noreferrer">
                    {a.title} ↗
                  </a>
                ) : a.has_file ? (
                  <a
                    href={`/api/v1/client-service/projects/${project.id}/attachments/${a.id}/file`}
                  >
                    {a.title} ↓
                  </a>
                ) : (
                  a.title
                )}
                <small>
                  {' '}
                  · {d.title} v{d.seq}
                </small>
              </p>
            )),
          )}
        {!project.deliveries.length && (
          <p>
            아직 전달된 자료가 없습니다. 프리랜서가 제출한 자료만 표시됩니다.
          </p>
        )}
      </section>
    </div>
  )
}
function MessageList({
  messages,
  live = false,
}: {
  messages: Message[]
  live?: boolean
}) {
  return (
    <div
      className="cs-message-list"
      role={live ? 'log' : undefined}
      aria-label={live ? '실시간 채팅 기록' : '메시지 기록'}
      aria-live={live ? 'polite' : undefined}
      aria-relevant="additions text"
    >
      {messages.map((m) => (
        <article className={`cs-message cs-message-${m.actor_side}`} key={m.id}>
          <div>
            <strong>{m.actor_name}</strong>
            <span>{m.actor_side === 'client' ? '클라이언트' : '프리랜서'}</span>
            <time dateTime={m.created_at}>
              {new Date(m.created_at).toLocaleString('ko-KR')}
            </time>
          </div>
          <p className="cs-pre">{m.body}</p>
        </article>
      ))}
      {!messages.length && (
        <p className="field-hint">아직 메시지가 없습니다.</p>
      )}
    </div>
  )
}
