import { useState } from 'react'
import {
  Link,
  Navigate,
  NavLink,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router'
import { useMe } from '../api/auth'
import {
  cs,
  useCS,
  type ClientProject,
  type Invitation,
  type Member,
  type Workspace,
} from '../api/clientService'
import {
  ActionForm,
  ErrorNotice,
  Input,
  Select,
  State,
  money,
  roles,
  str,
} from '../components/ClientServiceUI'
import { TaskCalendar } from '../components/TaskCalendar'

import { ExpertsView, ProfileEditor } from './ExpertsView'
import { InquiriesView } from './InquiriesView'
import { ClientProjectView } from './ClientProjectView'

export function ClientServicePage() {
  const location = useLocation()
  const { projectId } = useParams()
  const workspaces = useCS<Workspace[]>('/workspaces')
  const me = useMe()
  const [selected, setSelected] = useState(
    new URLSearchParams(location.search).get('workspace') ?? '',
  )
  const linkedProject = useCS<ClientProject>(
    `/projects/${projectId}`,
    !!projectId,
  )
  const wid =
    (projectId ? linkedProject.data?.workspace_id : null) ??
    workspaces.data?.find((w) => w.id === selected)?.id ??
    workspaces.data?.[0]?.id ??
    ''
  const current = workspaces.data?.find((w) => w.id === wid)
  const tab = location.pathname.split('/')[2] ?? 'experts'
  const navigate = useNavigate()
  return (
    <div className="cs-shell">
      <div className="cs-topline">
        <div>
          <p className="cs-eyebrow">CLIENT WORKSPACE · MVP</p>
          <h1>함께 만드는 다음 프로젝트</h1>
        </div>
        <label className="cs-workspace">
          워크스페이스
          <select
            className="input"
            value={wid}
            onChange={(e) => {
              setSelected(e.target.value)
              if (projectId) navigate('/client/projects')
            }}
          >
            <option value="">워크스페이스 선택</option>
            {workspaces.data?.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} · {roles.find((r) => r[0] === w.role)?.[1]}
              </option>
            ))}
          </select>
        </label>
      </div>
      <nav className="cs-tabs" aria-label="클라이언트 메뉴">
        {[
          ['experts', '전문가 찾기'],
          ['inquiries', '의뢰 관리'],
          ['dashboard', '대시보드'],
          ['projects', '프로젝트'],
          ['team', '팀 설정'],
        ].map(([v, l]) => (
          <NavLink to={`/client/${v}${wid ? `?workspace=${wid}` : ''}`} key={v}>
            {l}
          </NavLink>
        ))}
      </nav>
      <ErrorNotice error={workspaces.error} />
      {workspaces.isPending && <p role="status">워크스페이스를 불러오는 중…</p>}
      {!workspaces.isPending && !wid && !projectId && (
        <section className="cs-card cs-onboard">
          <h2>일을 맡길 공간을 만드세요</h2>
          <p>
            기업·팀 이름 또는 개인 이름으로 시작할 수 있습니다. 초대받았다면
            초대 링크를 열어 주세요.
          </p>
          <ActionForm
            title="워크스페이스 만들기"
            label="만들고 전문가 찾기"
            onSubmit={async (d) => {
              const w = await cs<Workspace>('POST', '/workspaces', {
                name: str(d, 'name'),
              })
              setSelected(w.id)
              navigate('/client/experts')
            }}
          >
            <Input label="기업·팀 또는 개인 이름" name="name" required />
          </ActionForm>
        </section>
      )}
      {tab === 'experts' && (
        <ExpertsView wid={wid} canInquire={current?.role !== 'viewer'} />
      )}
      {tab === 'dashboard' && wid && <ClientDashboard wid={wid} />}
      {tab === 'projects' && !projectId && wid && (
        <ClientDashboard wid={wid} listOnly />
      )}
      {projectId && <ClientProjectView id={projectId} />}
      {tab === 'inquiries' && wid && (
        <InquiriesView
          wid={wid}
          canAccept={current?.role === 'owner' || current?.role === 'admin'}
        />
      )}
      {tab === 'team' && wid && (
        <TeamSettings wid={wid} current={current!} meId={me.data?.id ?? ''} />
      )}
    </div>
  )
}
export function ClientHome() {
  const workspaces = useCS<Workspace[]>('/workspaces')
  const first = workspaces.data?.[0]?.id
  const projects = useCS<ClientProject[]>(
    `/workspaces/${first}/projects`,
    !!first,
  )
  if (workspaces.isPending || (first && projects.isPending))
    return <p role="status">이동할 화면을 확인하는 중…</p>
  if (workspaces.error || projects.error)
    return <ErrorNotice error={workspaces.error || projects.error} />
  return (
    <Navigate
      to={
        projects.data?.some((p) => p.status === 'active')
          ? '/client/dashboard'
          : '/client/experts'
      }
      replace
    />
  )
}
function ClientDashboard({
  wid,
  listOnly = false,
}: {
  wid: string
  listOnly?: boolean
}) {
  const projects = useCS<ClientProject[]>(`/workspaces/${wid}/projects`)
  const today = new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Seoul',
  }).format(new Date())
  const [month, setMonth] = useState(today.slice(0, 7))
  const data = projects.data ?? []
  const pending = data.flatMap((p) =>
    p.deliveries
      .filter((d) => d.current && d.state === 'pending')
      .map((d) => ({ p, d })),
  )
  const tasks = data.flatMap((p) =>
    p.tasks
      .filter((t) => t.status !== 'done' && t.due_date)
      .map((t) => ({ p, t })),
  )
  return (
    <>
      <div className="cs-section-head">
        <h2>{listOnly ? '우리 팀 프로젝트' : '지금 확인할 일'}</h2>
        <p>
          초대받은 프로젝트만 표시됩니다. 작업 완료와 결과물 승인은 별개입니다.
        </p>
      </div>
      <ErrorNotice error={projects.error} />
      {projects.isPending && <p role="status">프로젝트를 불러오는 중…</p>}
      {!listOnly && (
        <>
          <div className="cs-kpis">
            <div>
              <strong>
                {data.filter((p) => p.status === 'active').length}
              </strong>
              <span>진행 중 프로젝트</span>
            </div>
            <div>
              <strong>{pending.length}</strong>
              <span>검수 대기 결과물</span>
            </div>
            <div>
              <strong>
                {tasks.filter(({ t }) => t.due_date! < today).length}
              </strong>
              <span>기한이 지난 공개 일정</span>
            </div>
          </div>
          {tasks.some(({ t }) => t.label === '고객 자료') && (
            <section className="cs-card">
              <h3>우리 팀이 제공할 자료</h3>
              {tasks
                .filter(({ t }) => t.label === '고객 자료')
                .map(({ p, t }) => (
                  <Link
                    key={t.id}
                    to={`/client/projects/${p.id}`}
                    className="cs-task cs-material-link"
                  >
                    <strong>{t.title}</strong>
                    <span>
                      {t.due_date}까지 · {p.name}
                    </span>
                  </Link>
                ))}
            </section>
          )}
          <div className="cs-grid">
            {pending.map(({ p, d }) => (
              <Link
                key={d.id}
                to={`/client/projects/${p.id}`}
                className="cs-card"
              >
                <State value="pending" />
                <h3>
                  {d.title} · v{d.seq}
                </h3>
                <p>{p.name}</p>
                <p>
                  {d.due_date ? `${d.due_date}까지 검수` : '검수 기한 미정'}
                </p>
                <strong>
                  {p.can_approve ? '검수·승인하기 →' : '결과물 확인하기 →'}
                </strong>
              </Link>
            ))}
          </div>
        </>
      )}
      <div className="cs-grid">
        {data.map((p) => (
          <Link key={p.id} to={`/client/projects/${p.id}`} className="cs-card">
            <State value={p.status} />
            <h3>{p.name}</h3>
            <p>
              {p.freelancer_name} ·{' '}
              {p.due_date ? `${p.due_date} 마감` : '마감일 미정'}
            </p>
            {p.can_finance && <p>계약 기준 금액 {money(p.contract_amount)}</p>}
            <span className="cs-link">프로젝트 열기 →</span>
          </Link>
        ))}
      </div>
      {!projects.isPending && !projects.error && !data.length && (
        <div className="cs-empty">
          <h3>아직 연결된 프로젝트가 없습니다</h3>
          <p>
            전문가에게 의뢰하거나 프리랜서가 보낸 프로젝트 연결 초대를
            수락하세요. 관리자는 참여 권한 없이 프로젝트를 볼 수 없습니다.
          </p>
          <Link to="/client/experts" className="btn btn-primary">
            전문가 찾기
          </Link>
        </div>
      )}
      {!listOnly && (
        <section className="cs-card">
          <h2>팀 일정 캘린더</h2>
          <TaskCalendar
            month={month}
            onMonthChange={setMonth}
            today={today}
            entries={[
              ...tasks.map(({ p, t }) => ({
                id: t.id,
                title: t.title,
                dueDate: t.due_date!,
                status: t.status,
                subtitle: p.name,
                href: `/client/projects/${p.id}`,
              })),
              ...pending
                .filter(({ d }) => d.due_date)
                .map(({ p, d }) => ({
                  id: d.id,
                  title: `검수 · ${d.title}`,
                  dueDate: d.due_date!,
                  subtitle: p.name,
                  href: `/client/projects/${p.id}`,
                })),
            ]}
          />
        </section>
      )}
    </>
  )
}
function TeamSettings({
  wid,
  current,
  meId,
}: {
  wid: string
  current: Workspace
  meId: string
}) {
  const members = useCS<Member[]>(`/workspaces/${wid}/members`)
  const manage = ['owner', 'admin'].includes(current.role)
  const invites = useCS<Invitation[]>(`/workspaces/${wid}/invitations`, manage)
  const [link, setLink] = useState('')
  return (
    <>
      <div className="cs-section-head">
        <h2>팀과 접근 권한</h2>
        <p>
          관리자도 초대된 프로젝트만 열람합니다. 프로젝트별 참여자·승인자·금액
          권한은 해당 프로젝트에서 설정합니다.
        </p>
      </div>
      <ErrorNotice error={members.error} />
      <div className="cs-grid">
        <section className="cs-card">
          <h3>팀원</h3>
          {members.data?.map((m) => (
            <div className="cs-member" key={m.id}>
              <strong>
                {m.name}
                {m.id === meId && ' (나)'}
              </strong>
              <small>{m.email}</small>
              <span>{roles.find((r) => r[0] === m.role)?.[1]}</span>
              {manage && (m.role !== 'owner' || current.role === 'owner') && (
                <ActionForm
                  title={`${m.name} 역할 변경`}
                  label="역할 변경"
                  onSubmit={(d) =>
                    cs('PATCH', `/workspaces/${wid}/members/${m.id}`, {
                      role: str(d, 'role'),
                    })
                  }
                >
                  <Select
                    label="역할"
                    name="role"
                    value={m.role}
                    options={
                      current.role === 'owner'
                        ? roles
                        : roles.filter((r) => r[0] !== 'owner')
                    }
                  />
                </ActionForm>
              )}
              {(manage || m.id === meId) && (
                <ActionForm
                  title={`${m.name} 참여 해제`}
                  label={m.id === meId ? '팀 나가기' : '팀에서 제외'}
                  onSubmit={async () => {
                    if (
                      !window.confirm(
                        `${m.name} 님의 이 팀 접근 권한을 해제할까요?`,
                      )
                    )
                      return
                    await cs('DELETE', `/workspaces/${wid}/members/${m.id}`)
                  }}
                >
                  <p className="field-hint">
                    해제하면 프로젝트·파일 접근도 종료됩니다. 마지막 소유자는
                    나갈 수 없습니다.
                  </p>
                </ActionForm>
              )}
            </div>
          ))}
        </section>
        {manage && (
          <section className="cs-card">
            <ActionForm
              title="팀원 초대"
              label="초대 링크 만들기"
              onSubmit={async (d) => {
                const i = await cs<Invitation>(
                  'POST',
                  `/workspaces/${wid}/invitations`,
                  { email: str(d, 'email'), role: str(d, 'role') },
                )
                setLink(
                  `${location.origin}/client/invite?token=${encodeURIComponent(i.token!)}`,
                )
              }}
            >
              <Input label="초대할 이메일" name="email" type="email" required />
              <Select
                label="팀 역할"
                name="role"
                options={roles.filter((r) => r[0] !== 'owner')}
              />
              <p className="cs-note">
                이메일 발송 미연결 · 링크는 3일 후 만료되며, 해당 이메일
                계정으로 한 번만 수락할 수 있습니다.
              </p>
            </ActionForm>
            {link && (
              <label className="cs-field">
                <span>초대 링크 · 지금 복사해서 전달하세요</span>
                <input
                  className="input"
                  readOnly
                  value={link}
                  onFocus={(e) => e.target.select()}
                />
              </label>
            )}
            <ErrorNotice error={invites.error} />
            {invites.data?.map((i) => (
              <div className="cs-member" key={i.id}>
                <strong>{i.email}</strong>
                <span>
                  {i.used_at
                    ? '수락됨'
                    : i.revoked_at
                      ? '취소됨'
                      : new Date(i.expires_at) < new Date()
                        ? '만료됨'
                        : '수락 대기'}
                </span>
                {!i.used_at && !i.revoked_at && (
                  <ActionForm
                    title={`${i.email} 초대 취소`}
                    label="초대 취소"
                    onSubmit={() => cs('DELETE', `/invitations/${i.id}`)}
                  >
                    <small>기존 링크 사용을 막습니다.</small>
                  </ActionForm>
                )}
              </div>
            ))}
          </section>
        )}
      </div>
      <section className="cs-card">
        <ActionForm
          title="다른 워크스페이스 만들기"
          onSubmit={(d) => cs('POST', '/workspaces', { name: str(d, 'name') })}
        >
          <Input label="이름" name="name" required />
        </ActionForm>
      </section>
    </>
  )
}
export function ClientInvitePage() {
  const workspaces = useCS<Workspace[]>('/workspaces')
  const navigate = useNavigate()
  const token = new URLSearchParams(useLocation().search).get('token') ?? ''
  return (
    <section className="cs-card cs-invite">
      <h1>초대 수락</h1>
      <p>
        초대받은 이메일 계정으로 로그인했는지 확인하세요. 프로젝트 연결 초대라면
        연결할 워크스페이스를 선택하세요.
      </p>
      <ActionForm
        title="초대 확인"
        label="초대 수락"
        onSubmit={async (d) => {
          await cs('POST', '/invitations/accept', {
            token,
            workspace_id: str(d, 'wid') || null,
          })
          navigate('/client/dashboard')
        }}
      >
        <Select
          label="프로젝트를 연결할 워크스페이스"
          name="wid"
          options={[
            ['', '팀 초대인 경우 선택 불필요'],
            ...(workspaces.data ?? [])
              .filter((w) => ['owner', 'admin'].includes(w.role))
              .map((w) => [w.id, w.name] as [string, string]),
          ]}
        />
      </ActionForm>
      <Link to="/client/team">워크스페이스가 없다면 먼저 만들기</Link>
    </section>
  )
}
export { ProfileEditor }
