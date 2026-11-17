import { useState } from 'react'
import { Link } from 'react-router'
import { cs, useCS, type Profile, type Work } from '../api/clientService'
import { useMe } from '../api/auth'
import {
  ActionForm,
  Area,
  Check,
  ErrorNotice,
  Input,
  Select,
  money,
  str,
} from '../components/ClientServiceUI'
import { JOB_TYPE_LABELS } from '../lib/format'

const JOBS = Object.entries(JOB_TYPE_LABELS) as [string, string][]
const VAT: Record<string, string> = {
  excluded: '부가세 별도',
  included: '부가세 포함',
  not_applicable: '부가세 해당 없음',
}
export function ExpertsView({
  wid,
  canInquire,
}: {
  wid: string
  canInquire: boolean
}) {
  const [query, setQuery] = useState('')
  const [expertId, setExpertId] = useState('')
  const experts = useCS<Profile[]>(`/experts${query}`)
  const selected = experts.data?.find((p) => p.id === expertId)
  const me = useMe()
  return (
    <>
      <section className="cs-hero">
        <p className="cs-eyebrow">FIND YOUR NEXT COLLABORATOR</p>
        <h2>어떤 일을 맡기고 싶으세요?</h2>
        <p>
          작업물과 제공 범위를 비교하고, 프로젝트에 맞는 전문가에게 의뢰하세요.
        </p>
        <search>
          <ActionForm
            title="전문가 검색"
            label="조건으로 찾기"
            onSubmit={async (d) => {
              const params = new URLSearchParams()
              for (const key of ['q', 'job', 'budget', 'due'])
                if (str(d, key)) params.set(key, str(d, key))
              setQuery(`?${params}`)
              setExpertId('')
            }}
            className="cs-search"
          >
            <Input
              label="업무·이름 검색"
              name="q"
              hint="예: 굿즈, 브랜딩, 영상 편집"
            />
            <Select
              label="업무 분야"
              name="job"
              options={[['', '전체 분야'], ...JOBS]}
            />
            <Input label="최대 예산 (원)" name="budget" type="number" min="0" />
            <Input label="희망 납품일" name="due" type="date" />
          </ActionForm>
        </search>
      </section>
      <div className="cs-section-head">
        <h2>공개된 전문가</h2>
        <p>
          프리랜서가 직접 공개한 프로필입니다. 가격은 제시 조건이며 최종 견적은
          별도 협의합니다.
        </p>
      </div>
      <ErrorNotice error={experts.error} />
      {experts.isPending && <p role="status">전문가를 불러오는 중…</p>}
      <div className="cs-grid">
        {experts.data?.map((p) => (
          <article className="cs-card cs-expert" key={p.id}>
            {p.portfolio.find((w) => w.image_url) ? (
              <img
                src={p.portfolio.find((w) => w.image_url)!.image_url!}
                alt={`${p.name}의 대표 작업`}
                loading="lazy"
                referrerPolicy="no-referrer"
              />
            ) : (
              <div className="cs-cover">
                <span>
                  {JOB_TYPE_LABELS[
                    p.job_type as keyof typeof JOB_TYPE_LABELS
                  ] ?? p.job_type}
                </span>
                <strong>{p.name.slice(0, 1)}</strong>
              </div>
            )}
            <div className="cs-card-body">
              <small>{p.services.join(' · ')}</small>
              <h3>{p.name}</h3>
              <p>{p.headline}</p>
              <strong>
                {p.price_type === 'quote'
                  ? '견적 협의'
                  : `${money(p.price)}${p.price_type === 'from' ? '부터' : ''}`}
              </strong>
              <p className="field-hint">
                {VAT[p.vat]} · 수정 {p.revisions}회 ·{' '}
                {p.days ? `예상 ${p.days}일` : '기간 협의'}
              </p>
              <p>{p.scope}</p>
              <p className="field-hint">
                작업 가능: {p.available_from ?? '확인 필요'}
              </p>
              {p.reasons?.map((r) => (
                <small key={r} className="cs-reason">
                  {r}
                </small>
              ))}
              <button
                type="button"
                className="btn btn-secondary"
                aria-expanded={selected?.id === p.id}
                onClick={() => setExpertId(selected?.id === p.id ? '' : p.id)}
              >
                프로필·포트폴리오 보기
              </button>
            </div>
          </article>
        ))}
      </div>
      {!experts.isPending && !experts.error && !experts.data?.length && (
        <div className="cs-empty">
          <h3>조건에 맞는 공개 프로필이 없습니다</h3>
          <p>
            검색 조건을 바꾸거나 프리랜서가 프로필을 공개한 뒤 확인해 주세요.
            가상 전문가와 후기는 등록하지 않았습니다.
          </p>
          <Link to="/client-profile">내 프리랜서 프로필 작성하기</Link>
        </div>
      )}
      {selected && (
        <section className="cs-card cs-profile-detail">
          <h2>
            {selected.name} · {selected.headline}
          </h2>
          <p className="cs-pre">{selected.bio}</p>
          <dl className="cs-spec">
            <dt>제공 범위</dt>
            <dd>{selected.scope}</dd>
            <dt>제외 항목</dt>
            <dd>{selected.exclusions || '별도 확인'}</dd>
            <dt>원본 파일</dt>
            <dd>{selected.originals}</dd>
            <dt>사용 권한</dt>
            <dd>{selected.rights}</dd>
          </dl>
          <h3>포트폴리오</h3>
          <div className="cs-grid">
            {selected.portfolio.map((w, i) => (
              <article className="cs-card" key={i}>
                {w.image_url && (
                  <img
                    className="cs-work-image"
                    src={w.image_url}
                    alt={w.title}
                    loading="lazy"
                    referrerPolicy="no-referrer"
                  />
                )}
                <h4>{w.title}</h4>
                <p>{w.description}</p>
                <p>
                  <strong>담당 범위:</strong> {w.contribution}
                </p>
                {w.client_name && <p>고객: {w.client_name}</p>}
                {w.feedback && <blockquote>{w.feedback}</blockquote>}
                <a href={w.url} target="_blank" rel="noopener noreferrer">
                  외부 작업 보기 ↗
                </a>
              </article>
            ))}
          </div>
          {!selected.portfolio.length && <p>등록된 포트폴리오가 없습니다.</p>}
          {wid && canInquire && selected.id !== me.data?.id && (
            <ActionForm
              key={selected.id}
              title="이 전문가에게 의뢰하기"
              label="의뢰 작성 중으로 저장"
              onSubmit={async (d) => {
                await cs('POST', `/workspaces/${wid}/inquiries`, {
                  freelancer_id: selected.id,
                  title: str(d, 'title'),
                  purpose: str(d, 'purpose'),
                  scope: str(d, 'scope'),
                  deliverables: str(d, 'deliverables'),
                  budget: str(d, 'budget') || null,
                  due_date: str(d, 'due_date') || null,
                  references: str(d, 'references'),
                  send: d.has('send'),
                })
              }}
            >
              <Input label="프로젝트 이름" name="title" required />
              <Area label="목적·사용처" name="purpose" required />
              <Area label="필요한 업무와 수량" name="scope" required />
              <Area
                label="받고 싶은 결과물·파일·사용 범위"
                name="deliverables"
                required
              />
              <Input
                label="예산 상한 (원)"
                name="budget"
                type="number"
                min="0"
              />
              <Input label="희망 납품일" name="due_date" type="date" />
              <Area
                label="참고 자료·아직 결정하지 못한 사항"
                name="references"
              />
              <Check
                label="저장과 동시에 전문가에게 의뢰 전송 (외부 이메일은 발송되지 않습니다)"
                name="send"
              />
            </ActionForm>
          )}
          {!wid && <p>의뢰하려면 먼저 워크스페이스를 만들어 주세요.</p>}
          {selected.id === me.data?.id && (
            <Link to="/client-profile">내 프로필 수정</Link>
          )}
        </section>
      )}
    </>
  )
}
export function ProfileEditor() {
  const profile = useCS<Profile | Record<string, never>>('/profile')
  const me = useMe()
  const [works, setWorks] = useState<Work[]>([])
  const [editingWorks, setEditingWorks] = useState(false)
  const [resetKey, setResetKey] = useState(0)
  if (profile.isPending) return <p role="status">프로필을 불러오는 중…</p>
  if (profile.error) return <ErrorNotice error={profile.error} />
  const p = profile.data as Partial<Profile>
  const portfolio = editingWorks ? works : (p.portfolio ?? [])
  return (
    <div className="cs-shell">
      <p className="cs-eyebrow">FREELANCER PROFILE</p>
      <h1>나를 찾을 수 있는 프로필</h1>
      <p>
        직접 공개한 정보만 전문가 찾기에 나타납니다. 기존 프로젝트와 고객 파일은
        자동으로 공개되지 않습니다.
      </p>
      <div className="cs-two-columns">
        <section className="cs-card">
          <ActionForm
            key={p.id ?? 'new'}
            title="전문 업무와 서비스"
            label="프로필 저장"
            onSubmit={(d) =>
              cs('PUT', '/profile', {
                published: d.has('published'),
                headline: str(d, 'headline'),
                bio: str(d, 'bio'),
                job_type: str(d, 'job_type'),
                services: str(d, 'services')
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean),
                scope: str(d, 'scope'),
                price: str(d, 'price') || null,
                price_type: str(d, 'price_type'),
                vat: str(d, 'vat'),
                exclusions: str(d, 'exclusions'),
                revisions: Number(str(d, 'revisions')),
                days: str(d, 'days') ? Number(str(d, 'days')) : null,
                available_from: str(d, 'available_from') || null,
                originals: str(d, 'originals'),
                rights: str(d, 'rights'),
                portfolio,
              })
            }
          >
            <Input
              label="한 줄 소개"
              name="headline"
              value={p.headline}
              required
            />
            <Area label="경력·전문성·협업 방식" name="bio" value={p.bio} />
            <Select
              label="분야"
              name="job_type"
              value={p.job_type ?? me.data?.job_type}
              options={JOBS}
            />
            <Input
              label="제공 업무 (쉼표로 구분)"
              name="services"
              value={p.services?.join(', ')}
              required
            />
            <Area
              label="가격에 포함된 범위·수량"
              name="scope"
              value={p.scope}
              required
            />
            <Select
              label="가격 방식"
              name="price_type"
              value={p.price_type ?? 'quote'}
              options={[
                ['quote', '견적 협의'],
                ['fixed', '정액'],
                ['from', '시작 가격'],
              ]}
            />
            <Input
              label="제시 금액 (원)"
              name="price"
              type="number"
              min="0"
              value={p.price ?? ''}
            />
            <Select
              label="부가세"
              name="vat"
              value={p.vat}
              options={Object.entries(VAT)}
            />
            <Area
              label="제외 비용 (제작·인쇄비 등)"
              name="exclusions"
              value={p.exclusions}
            />
            <Input
              label="포함 수정 횟수"
              name="revisions"
              type="number"
              min="0"
              max="99"
              value={p.revisions ?? 0}
            />
            <Input
              label="예상 작업일 수"
              name="days"
              type="number"
              min="1"
              max="365"
              value={p.days ?? ''}
            />
            <Input
              label="작업 가능 시작일"
              name="available_from"
              type="date"
              value={p.available_from ?? ''}
            />
            <Input
              label="원본 파일 제공 조건"
              name="originals"
              value={p.originals ?? '별도 협의'}
              required
            />
            <Area
              label="사용 권한"
              name="rights"
              value={p.rights ?? '별도 협의'}
              required
            />
            <Check
              label="이 프로필과 아래 작업을 전문가 찾기에 공개합니다"
              name="published"
              checked={p.published}
            />
            <p className="field-hint">
              작업을 추가·제거한 뒤 이 저장 버튼을 눌러야 반영됩니다.
            </p>
          </ActionForm>
        </section>
        <section className="cs-card">
          <h2>외부 작업 포트폴리오</h2>
          {portfolio.map((w, i) => (
            <article className="cs-member" key={i}>
              <h3>{w.title}</h3>
              <p>{w.description}</p>
              <p>본인 담당: {w.contribution}</p>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => {
                  setWorks(portfolio.filter((_, j) => j !== i))
                  setEditingWorks(true)
                }}
              >
                프로필에서 제거
              </button>
            </article>
          ))}
          <ActionForm
            key={resetKey}
            title="작업 추가"
            label="목록에 추가 (프로필 저장 필요)"
            onSubmit={async (d) => {
              const w: Work = {
                title: str(d, 'title'),
                description: str(d, 'description'),
                contribution: str(d, 'contribution'),
                url: str(d, 'url'),
                image_url: str(d, 'image_url') || null,
                client_name: str(d, 'client_name'),
                feedback: str(d, 'feedback'),
                assets_consent: d.has('assets_consent'),
                client_name_consent: d.has('client_name_consent'),
                feedback_consent: d.has('feedback_consent'),
              }
              if (
                !w.assets_consent ||
                (w.client_name && !w.client_name_consent) ||
                (w.feedback && !w.feedback_consent)
              )
                throw new Error('공개 동의 확인 필요')
              setWorks([...portfolio, w])
              setEditingWorks(true)
              setResetKey((k) => k + 1)
            }}
          >
            <Input label="작업명" name="title" required />
            <Area label="작업 목적·결과물 설명" name="description" required />
            <Area label="본인이 맡은 범위" name="contribution" required />
            <Input label="공개 작업 URL" name="url" type="url" required />
            <Input label="공개 이미지 URL (선택)" name="image_url" type="url" />
            <Input label="고객 이름 (선택)" name="client_name" />
            <Area label="고객 피드백 (선택)" name="feedback" />
            <Check
              label="작업물 공개 권한을 확인했습니다 (필수)"
              name="assets_consent"
            />
            <Check
              label="고객 이름 공개 허락을 받았습니다 (이름 입력 시 필수)"
              name="client_name_consent"
            />
            <Check
              label="피드백 공개 허락을 받았습니다 (피드백 입력 시 필수)"
              name="feedback_consent"
            />
          </ActionForm>
        </section>
      </div>
      <Link to="/client/experts">전문가 찾기에서 확인 →</Link>
    </div>
  )
}
