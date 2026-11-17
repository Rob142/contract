import { ProjectConversation } from '../components/ProjectConversation'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  cs,
  useCS,
  type ClientProject,
  type Grant,
  type Invitation,
  type Member,
} from '../api/clientService'
import {
  ActionForm,
  Area,
  Check,
  ErrorNotice,
  Input,
  Select,
  State,
  money,
  str,
} from '../components/ClientServiceUI'
import { TaskCalendar } from '../components/TaskCalendar'
import { QuoteDetails } from './InquiriesView'

const todayKey = () =>
  new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(
    new Date(),
  )
export function ClientProjectView({ id }: { id: string }) {
  const result = useCS<ClientProject>(`/projects/${id}`)
  const [params, setParams] = useSearchParams()
  const requestedTab = params.get('tab') ?? 'overview'
  const tab = [
    'overview',
    'schedule',
    'deliveries',
    'conversation',
    'finance',
    'members',
  ].includes(requestedTab)
    ? requestedTab
    : 'overview'
  const setTab = (value: string) =>
    setParams(
      (previous) => {
        const next = new URLSearchParams(previous)
        next.set('tab', value)
        return next
      },
      { replace: true },
    )
  const [month, setMonth] = useState(todayKey().slice(0, 7))
  const p = result.data
  if (result.isPending) return <p role="status">프로젝트를 불러오는 중…</p>
  if (result.error || !p)
    return <ErrorNotice error={result.error ?? new Error()} />
  const current = p.deliveries.filter((d) => d.current)
  return (
    <div className="cs-project">
      <div className="cs-section-head">
        <div>
          <State value={p.status} />
          <h2>{p.name}</h2>
          <p>
            {p.freelancer_name} · {p.due_date ?? '마감일 미정'}
          </p>
        </div>
        {p.owner && (
          <Link className="btn btn-secondary" to={`/projects/${id}`}>
            프리랜서 작업 관리
          </Link>
        )}
      </div>
      <nav className="cs-tabs" aria-label="프로젝트 메뉴">
        {[
          ['overview', '개요'],
          ['schedule', '일정·작업'],
          ['deliveries', '결과물·검수'],
          ['conversation', '대화·자료'],
          ['finance', '계약·정산'],
          ['members', '참여자'],
        ].map(([v, l]) => (
          <button
            className={tab === v ? 'active' : ''}
            key={v}
            type="button"
            aria-pressed={tab === v}
            onClick={() => setTab(v!)}
          >
            {l}
          </button>
        ))}
      </nav>
      {tab === 'overview' && (
        <>
          <div className="cs-kpis">
            <div>
              <strong>
                {p.tasks.filter((t) => t.status === 'done').length}/
                {p.tasks.length}
              </strong>
              <span>{p.owner ? '전체 작업 완료' : '공개 작업 완료'}</span>
            </div>
            <div>
              <strong>
                {current.filter((d) => d.state === 'pending').length}
              </strong>
              <span>검수 대기 결과물</span>
            </div>
            <div>
              <strong>
                {p.revisions.used}
                {p.revisions.included == null ? '' : `/${p.revisions.included}`}
              </strong>
              <span>공식 수정 요청</span>
            </div>
          </div>
          <div className="cs-card">
            <h3>지금 필요한 행동</h3>
            {current.some((d) => d.state === 'pending') ? (
              <>
                <p>
                  제출된 결과물의 최신 버전을 확인하세요.{' '}
                  {p.can_approve
                    ? '최종 승인자로 지정되어 있습니다.'
                    : '의견을 남기고 지정된 승인자에게 결정을 요청하세요.'}
                </p>
                <button
                  className="btn btn-primary"
                  type="button"
                  onClick={() => setTab('deliveries')}
                >
                  결과물 확인
                </button>
              </>
            ) : (
              <p>현재 검수 대기 중인 결과물이 없습니다.</p>
            )}
            <p>
              작업 카드의 완료와 결과물 승인은 별도로 기록됩니다. 응답 지연으로
              자동 승인되지 않습니다.
            </p>
            {!p.approver_id && (
              <p className="alert">
                최종 승인자가 지정되지 않았습니다. 참여자 화면에서 지정해
                주세요.
              </p>
            )}
          </div>
        </>
      )}
      {tab === 'schedule' && (
        <section className="cs-card">
          <TaskCalendar
            month={month}
            onMonthChange={setMonth}
            today={todayKey()}
            entries={[
              ...p.tasks
                .filter((t) => t.due_date)
                .map((t) => ({
                  id: t.id,
                  title: t.title,
                  dueDate: t.due_date!,
                  status: t.status,
                })),
              ...current
                .filter((d) => d.state === 'pending' && d.due_date)
                .map((d) => ({
                  id: d.id,
                  title: `검수 · ${d.title}`,
                  dueDate: d.due_date!,
                })),
            ]}
            onOpen={(entryId) => {
              if (p.deliveries.some((d) => d.id === entryId))
                setTab('deliveries')
            }}
          />
          {p.tasks.map((t) => (
            <div className="cs-task" key={t.id}>
              <div>
                <State value={t.status} />
                <strong>{t.title}</strong>
                <small>{t.due_date ? `${t.due_date}까지` : '기한 없음'}</small>
              </div>
              {p.can_write &&
                t.label === '고객 자료' &&
                t.status !== 'done' && (
                  <ActionForm
                    title={`${t.title} 완료`}
                    label="자료 제공 완료"
                    onSubmit={() =>
                      cs('POST', `/projects/${p.id}/tasks/${t.id}/complete`)
                    }
                  >
                    <small>자료를 전달한 후 완료해 주세요.</small>
                  </ActionForm>
                )}
            </div>
          ))}
          {!p.tasks.length && (
            <p>공개된 일정이 없습니다. 프리랜서가 공개한 일정만 표시됩니다.</p>
          )}
        </section>
      )}
      {tab === 'deliveries' && (
        <>
          <p className="cs-note">
            댓글·확인은 수정 횟수에 포함되지 않습니다. 최종 승인자가 의견을
            취합해 ‘수정 요청 제출’을 할 때 1회로 기록됩니다.
          </p>
          {!p.deliveries.length && (
            <div className="cs-empty">
              <h3>전달된 결과물이 없습니다</h3>
              <p>
                작업 카드 연결 여부와 관계없이, 프리랜서가 제출한 결과물은
                이곳에 모입니다. 내부 파일은 표시되지 않습니다.
              </p>
            </div>
          )}
          {[...p.deliveries].reverse().map((d) => (
            <section className="cs-card" key={d.id}>
              <div className="cs-section-head">
                <div>
                  <h3>
                    {d.title} · v{d.seq}
                    {!d.current && ' · 이전 버전'}
                  </h3>
                  <State value={d.state} />
                  <p>
                    제출 {new Date(d.created_at).toLocaleString('ko-KR')} · 검수{' '}
                    {d.due_date ?? '기한 미정'}
                  </p>
                </div>
              </div>
              <p className="cs-pre">{d.payload.note}</p>
              <ul className="cs-files">
                {d.payload.attachments.map((a) => (
                  <li key={a.id}>
                    {a.url ? (
                      <a href={a.url} target="_blank" rel="noopener noreferrer">
                        {a.title} ↗
                      </a>
                    ) : a.has_file ? (
                      <a
                        href={`/api/v1/client-service/projects/${p.id}/attachments/${a.id}/file`}
                      >
                        {a.title} ↓ 다운로드
                      </a>
                    ) : (
                      a.title
                    )}
                  </li>
                ))}
              </ul>
              <div className="cs-messages">
                {d.events.map((e) => (
                  <div key={e.id}>
                    <strong>
                      {e.actor_name} · {e.workspace_name}
                    </strong>
                    <small>
                      {new Date(e.created_at).toLocaleString('ko-KR')}
                    </small>
                    <State value={e.kind} />
                    {e.body && <p className="cs-pre">{e.body}</p>}
                  </div>
                ))}
              </div>
              {p.can_write && (
                <ActionForm
                  title={`v${d.seq} 의견 남기기`}
                  label="의견 남기기"
                  onSubmit={(data) =>
                    cs('POST', `/versions/${d.id}/reviews`, {
                      kind: 'comment',
                      body: str(data, 'body'),
                    })
                  }
                >
                  <Area
                    label="의견 (수정 횟수 차감 없음)"
                    name="body"
                    required
                  />
                </ActionForm>
              )}
              {p.can_write && !p.owner && (
                <ActionForm
                  title={`v${d.seq} 열람 확인`}
                  label="확인했어요"
                  onSubmit={() =>
                    cs('POST', `/versions/${d.id}/reviews`, { kind: 'seen' })
                  }
                >
                  <small>열람 확인이며 승인이 아닙니다.</small>
                </ActionForm>
              )}
              {p.can_approve && d.current && d.state === 'pending' && (
                <div className="cs-review-actions">
                  <ActionForm
                    title="취합된 수정 요청"
                    label="수정 요청 제출 · 1회 기록"
                    onSubmit={(data) =>
                      cs('POST', `/versions/${d.id}/reviews`, {
                        kind: 'changes',
                        body: str(data, 'body'),
                      })
                    }
                  >
                    <Area
                      label="팀 의견을 취합한 수정 사항"
                      name="body"
                      required
                    />
                  </ActionForm>
                  <ActionForm
                    title="최종 승인"
                    label={`v${d.seq} 승인`}
                    onSubmit={async (data) => {
                      if (!data.has('confirm')) return
                      await cs('POST', `/versions/${d.id}/reviews`, {
                        kind: 'approved',
                      })
                    }}
                  >
                    <label className="checkbox">
                      <input type="checkbox" name="confirm" required />이 버전의
                      결과물을 확인했고 승인합니다.
                    </label>
                    <small>
                      승인 기록은 보존됩니다. 자동 결제나 청구서 발송은 하지
                      않습니다.
                    </small>
                  </ActionForm>
                </div>
              )}
            </section>
          ))}
        </>
      )}
      {tab === 'conversation' && <ProjectConversation key={p.id} project={p} />}
      {tab === 'finance' && (
        <section className="cs-card">
          <h3>계약 기준과 청구 근거</h3>
          {!p.can_finance ? (
            <p>
              금액·계약 조건 열람 권한이 없습니다. 프로젝트 담당자에게
              요청하세요.
            </p>
          ) : (
            <>
              <p>
                계약 기준 금액: <strong>{money(p.contract_amount)}</strong>
              </p>
              {p.agreement ? (
                <>
                  <h4>확정 견적 v{p.agreement.seq}</h4>
                  <QuoteDetails q={p.agreement.payload} />
                  <p>
                    수락{' '}
                    {new Date(p.agreement.accepted_at).toLocaleString('ko-KR')}
                  </p>
                </>
              ) : (
                <p>
                  기존 프로젝트의 계약 조건은 프리랜서와 확인해 주세요. 새
                  견적을 통해 확정한 조건은 이곳에 보존됩니다.
                </p>
              )}
              <h4>승인 기록</h4>
              {p.deliveries
                .filter((d) => d.state === 'approved')
                .map((d) => (
                  <p key={d.id}>
                    {d.title} v{d.seq} ·{' '}
                    {d.events.find((e) => e.kind === 'approved')?.actor_name}{' '}
                    승인
                  </p>
                ))}
              <p>
                계약에서 요구하는 최종 승인은 해당 버전 기록을 청구 근거로
                확인하세요. 실제 입금 여부나 결제 완료를 자동으로 표시하지
                않습니다.
              </p>
              {p.extra_quotes.map((q) => (
                <div className="cs-member" key={q.id}>
                  <h4>
                    {q.title} · {money(q.amount)}
                  </h4>
                  <p>{q.description}</p>
                  <p>
                    {q.accepted ? '클라이언트 수락 기록 있음' : '수락 대기'}
                  </p>
                  {p.can_approve && !q.accepted && (
                    <ActionForm
                      title="추가 견적 수락"
                      label="추가 견적 수락"
                      onSubmit={async () => {
                        if (
                          window.confirm(
                            '표시된 범위와 금액의 추가 견적을 수락할까요?',
                          )
                        )
                          await cs('POST', `/extra-quotes/${q.id}/accept`)
                      }}
                    >
                      <small>수락 시점의 견적 내용이 보존됩니다.</small>
                    </ActionForm>
                  )}
                </div>
              ))}
            </>
          )}
        </section>
      )}
      {tab === 'members' && <ProjectMembers p={p} />}
    </div>
  )
}
function ProjectMembers({ p }: { p: ClientProject }) {
  const grants = useCS<Grant[]>(`/projects/${p.id}/members`)
  const team = useCS<Member[]>(
    `/workspaces/${p.workspace_id}/members`,
    !!p.workspace_id && p.can_manage,
  )
  return (
    <section className="cs-card">
      <h3>프로젝트 참여자</h3>
      <p>
        팀 관리자도 참여자로 지정되어야 내용을 봅니다. 최종 승인자는 1명이며
        금액 열람 권한은 별도입니다.
      </p>
      <ErrorNotice error={grants.error} />
      {grants.data?.map((g) => (
        <div className="cs-member" key={g.id}>
          <strong>{g.name}</strong>
          <p>
            {g.approver ? '최종 승인자' : '참여자'} ·{' '}
            {g.can_finance ? '금액 열람 가능' : '금액 비공개'}
          </p>
          {p.can_manage && (
            <ActionForm
              title={`${g.name} 프로젝트 권한 해제`}
              label="프로젝트에서 제외"
              onSubmit={async () => {
                if (
                  window.confirm('이 프로젝트와 파일의 접근 권한을 해제할까요?')
                )
                  await cs('DELETE', `/projects/${p.id}/members/${g.id}`)
              }}
            >
              <small>팀 소속은 유지됩니다.</small>
            </ActionForm>
          )}
        </div>
      ))}
      {p.can_manage && p.workspace_id && (
        <ActionForm
          title="참여자 추가·권한 변경"
          onSubmit={(d) =>
            cs('POST', `/projects/${p.id}/members`, {
              user_id: str(d, 'user_id'),
              can_finance: d.has('can_finance'),
              approver: d.has('approver'),
            })
          }
        >
          <Select
            label="팀원"
            name="user_id"
            options={(team.data ?? []).map((m) => [
              m.id,
              `${m.name} · ${m.role}`,
            ])}
          />
          <Check label="금액·계약 조건 열람 허용" name="can_finance" />
          <Check
            label="최종 승인자로 지정 (기존 승인자는 참여자로 유지)"
            name="approver"
          />
        </ActionForm>
      )}
      {!p.workspace_id && (
        <p>아직 클라이언트 워크스페이스에 연결되지 않았습니다.</p>
      )}
    </section>
  )
}
export function FreelancerClientPanel({ id }: { id: string }) {
  const p = useCS<ClientProject>(`/projects/${id}`)
  const attachments = useCS<{ id: string; title: string; kind: string }[]>(
    `/projects/${id}/owner-attachments`,
  )
  const [invite, setInvite] = useState('')
  if (p.isPending) return <p role="status">클라이언트 연결을 불러오는 중…</p>
  if (p.error || !p.data) return <ErrorNotice error={p.error} />
  const data = p.data
  return (
    <section className="cs-card">
      <h2>클라이언트 협업 · MVP</h2>
      <p>
        내부 작업과 파일은 자동 공개하지 않습니다. 아래에서 공개할 일정과 제출할
        결과물을 선택하세요.
      </p>
      {!data.workspace_id && (
        <>
          <ActionForm
            title="기존 프로젝트를 클라이언트와 연결"
            label="연결 초대 링크 만들기"
            onSubmit={async (d) => {
              const i = await cs<Invitation>(
                'POST',
                `/projects/${id}/connection-invitations`,
                { email: str(d, 'email') },
              )
              setInvite(
                `${location.origin}/client/invite?token=${encodeURIComponent(i.token!)}`,
              )
            }}
          >
            <Input
              label="클라이언트 담당자 이메일"
              name="email"
              type="email"
              required
            />
            <p className="field-hint">
              담당자가 회사 워크스페이스를 선택해 수락하면 연결됩니다. 이메일
              발송은 아직 연결하지 않았습니다.
            </p>
          </ActionForm>
          {invite && (
            <label className="cs-field">
              <span>연결 초대 링크</span>
              <input
                className="input"
                readOnly
                value={invite}
                onFocus={(e) => e.target.select()}
              />
            </label>
          )}
        </>
      )}
      <details>
        <summary>클라이언트 공개 일정 설정</summary>
        <ActionForm
          title="공개할 작업"
          label="공개 일정 저장"
          onSubmit={(d) =>
            cs('PUT', `/projects/${id}/published-tasks`, {
              task_ids: d.getAll('tasks'),
            })
          }
        >
          {data.tasks.map((t) => (
            <Check
              key={t.id}
              name="tasks"
              value={t.id}
              label={`${t.title} · ${t.due_date ?? '기한 없음'}`}
              checked={t.client_visible}
            />
          ))}
          <p className="field-hint">
            일정 제목·상태·기한만 공개됩니다. 내부 메모·단가·체크리스트는
            공개되지 않습니다.
          </p>
        </ActionForm>
      </details>
      <ActionForm
        title="결과물 제출·새 버전 전달"
        label="선택한 결과물을 클라이언트에게 제출"
        onSubmit={(d) =>
          cs('POST', `/projects/${id}/deliveries`, {
            title: str(d, 'title'),
            note: str(d, 'note'),
            attachment_ids: d.getAll('attachments'),
            due_date: str(d, 'due_date') || null,
            delivery_id: str(d, 'delivery_id') || null,
          })
        }
      >
        <Select
          label="결과물 묶음"
          name="delivery_id"
          options={[
            ['', '새 결과물'],
            ...data.deliveries
              .filter((v) => v.current)
              .map(
                (v) =>
                  [v.delivery_id, `${v.title} · 다음 버전`] as [string, string],
              ),
          ]}
        />
        <Input label="결과물 제목 (새 결과물에 적용)" name="title" required />
        <Area label="제출 설명·이번 변경 사항" name="note" />
        <Input label="검수 요청 기한" name="due_date" type="date" />
        <fieldset>
          <legend>전달할 첨부 결과물 (1개 이상)</legend>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => void attachments.refetch()}
          >
            첨부 목록 새로고침
          </button>
          {attachments.data
            ?.filter((a) => a.kind === 'deliverable')
            .map((a) => (
              <Check
                key={a.id}
                name="attachments"
                value={a.id}
                label={a.title}
              />
            ))}
          {!attachments.data?.length && (
            <p>먼저 기존 결과물·첨부 영역에서 파일이나 링크를 추가해 주세요.</p>
          )}
        </fieldset>
        <p className="cs-note">
          제출된 버전의 파일은 이력 보존을 위해 삭제할 수 없습니다. 새 버전으로
          변경하세요.
        </p>
      </ActionForm>
      <Link to={`/client/projects/${id}`} className="btn btn-secondary">
        제출 이력·고객 의견 확인
      </Link>
    </section>
  )
}
