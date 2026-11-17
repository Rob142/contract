import { useState } from 'react'
import { Link } from 'react-router'
import {
  cs,
  useCS,
  type Inquiry,
  type QuotePayload,
} from '../api/clientService'
import {
  ActionForm,
  Area,
  ErrorNotice,
  Input,
  Select,
  State,
  money,
  str,
} from '../components/ClientServiceUI'

export function QuoteDetails({ q }: { q: QuotePayload }) {
  return (
    <dl className="cs-spec">
      <dt>견적 금액</dt>
      <dd>
        {money(q.amount)} ·{' '}
        {q.vat === 'excluded'
          ? '부가세 별도'
          : q.vat === 'included'
            ? '부가세 포함'
            : '부가세 해당 없음'}
      </dd>
      <dt>작업 범위</dt>
      <dd>{q.scope}</dd>
      <dt>결과물·수량</dt>
      <dd>{q.deliverables}</dd>
      <dt>제외 항목·추가 비용</dt>
      <dd>{q.exclusions}</dd>
      <dt>수정 횟수</dt>
      <dd>{q.revisions}회</dd>
      <dt>자료 제공일</dt>
      <dd>{q.client_due_date}</dd>
      <dt>납품일</dt>
      <dd>{q.due_date}</dd>
      <dt>지급 조건</dt>
      <dd>{q.payment}</dd>
      <dt>사용 권한</dt>
      <dd>{q.rights}</dd>
      <dt>원본 파일</dt>
      <dd>{q.originals}</dd>
    </dl>
  )
}
export function InquiriesView({
  wid,
  canAccept = false,
}: {
  wid?: string
  canAccept?: boolean
}) {
  const inquiries = useCS<Inquiry[]>(`/inquiries${wid ? `?wid=${wid}` : ''}`)
  const [open, setOpen] = useState('')
  const rows = inquiries.data ?? []
  return (
    <>
      <div className="cs-section-head">
        <h2>{wid ? '보낸 의뢰와 견적' : '받은 클라이언트 의뢰'}</h2>
        <p>
          의뢰 전송으로 계약이 확정되지 않습니다. 협의 후 최신 견적을 확인하고
          확정하세요.
        </p>
      </div>
      <ErrorNotice error={inquiries.error} />
      {inquiries.isPending && <p role="status">의뢰를 불러오는 중…</p>}
      {!inquiries.isPending && !inquiries.error && !rows.length && (
        <div className="cs-empty">
          <h3>아직 의뢰가 없습니다</h3>
          <p>
            {wid
              ? '전문가 프로필에서 의뢰를 작성하면 이곳에서 확인할 수 있습니다.'
              : '공개 프로필을 등록하면 클라이언트가 의뢰를 보낼 수 있습니다.'}
          </p>
          <Link
            to={wid ? '/client/experts' : '/client-profile'}
            className="btn btn-primary"
          >
            {wid ? '전문가 찾기' : '프로필 작성'}
          </Link>
        </div>
      )}
      <div className="cs-stack">
        {rows.map((i) => (
          <section className="cs-card" key={i.id}>
            <div className="cs-section-head">
              <div>
                <State value={i.status} />
                <h3>{i.payload.title}</h3>
                <p>{wid ? i.freelancer_name : i.client_name}</p>
              </div>
              <button
                className="btn btn-secondary"
                type="button"
                aria-expanded={open === i.id}
                onClick={() => setOpen(open === i.id ? '' : i.id)}
              >
                {open === i.id ? '접기' : '의뢰·견적 보기'}
              </button>
            </div>
            {open === i.id && (
              <>
                {i.status === 'draft' && wid && (
                  <ActionForm
                    title=" 의뢰 초안 수정"
                    label="초안 저장"
                    onSubmit={(d) =>
                      cs('PUT', `/inquiries/${i.id}`, {
                        freelancer_id: i.freelancer_id,
                        title: str(d, 'title'),
                        purpose: str(d, 'purpose'),
                        scope: str(d, 'scope'),
                        deliverables: str(d, 'deliverables'),
                        budget: str(d, 'budget') || null,
                        due_date: str(d, 'due_date') || null,
                        references: str(d, 'references'),
                      })
                    }
                  >
                    <Input
                      label="프로젝트 이름"
                      name="title"
                      value={i.payload.title}
                      required
                    />
                    <Area
                      label="목적·사용처"
                      name="purpose"
                      value={i.payload.purpose}
                      required
                    />
                    <Area
                      label="업무 범위"
                      name="scope"
                      value={i.payload.scope}
                      required
                    />
                    <Area
                      label="결과물"
                      name="deliverables"
                      value={i.payload.deliverables}
                      required
                    />
                    <Input
                      label="예산 상한 (원)"
                      name="budget"
                      type="number"
                      min="0"
                      value={i.payload.budget ?? ''}
                    />
                    <Input
                      label="희망 납품일"
                      name="due_date"
                      type="date"
                      value={i.payload.due_date ?? ''}
                    />
                    <Area
                      label="참고 자료"
                      name="references"
                      value={i.payload.references}
                    />
                  </ActionForm>
                )}
                <dl className="cs-spec">
                  <dt>목적</dt>
                  <dd>{i.payload.purpose}</dd>
                  <dt>업무 범위</dt>
                  <dd>{i.payload.scope}</dd>
                  <dt>결과물</dt>
                  <dd>{i.payload.deliverables}</dd>
                  <dt>예산 상한</dt>
                  <dd>{money(i.payload.budget)}</dd>
                  <dt>희망 납품일</dt>
                  <dd>{i.payload.due_date ?? '협의'}</dd>
                  <dt>참고 자료</dt>
                  <dd>{i.payload.references || '없음'}</dd>
                </dl>
                {i.status === 'draft' && wid && (
                  <ActionForm
                    title="작성한 의뢰 전송"
                    label="전문가에게 전송"
                    onSubmit={() => cs('POST', `/inquiries/${i.id}/send`)}
                  >
                    <p>
                      전송 후 전문가가 의뢰 내용을 확인할 수 있습니다. 외부
                      이메일은 발송되지 않습니다.
                    </p>
                  </ActionForm>
                )}
                {i.status !== 'draft' && (
                  <>
                    <h4>협의 기록</h4>
                    <div className="cs-messages">
                      {i.messages.map((m) => (
                        <div key={m.id}>
                          <strong>{m.actor_name}</strong>
                          <small>
                            {new Date(m.created_at).toLocaleString('ko-KR')}
                          </small>
                          <p className="cs-pre">{m.body}</p>
                        </div>
                      ))}
                      {!i.messages.length && (
                        <p>아직 협의 메시지가 없습니다.</p>
                      )}
                    </div>
                    <ActionForm
                      title="협의 메시지 남기기"
                      label="메시지 전송"
                      onSubmit={(d) =>
                        cs('POST', `/inquiries/${i.id}/messages`, {
                          body: str(d, 'body'),
                        })
                      }
                    >
                      <Area label="협의 내용" name="body" required />
                    </ActionForm>
                  </>
                )}
                <h4>견적 버전</h4>
                {i.quotes.map((q, index) => (
                  <details
                    className="cs-quote"
                    key={q.id}
                    open={index === i.quotes.length - 1}
                  >
                    <summary>
                      견적 v{q.seq} · {money(q.payload.amount)} ·{' '}
                      {q.accepted_at
                        ? '계약 확정'
                        : index === i.quotes.length - 1
                          ? '최신 제안'
                          : '이전 제안'}
                    </summary>
                    <QuoteDetails q={q.payload} />
                    {q.accepted_at && (
                      <p>
                        수락 시각:{' '}
                        {new Date(q.accepted_at).toLocaleString('ko-KR')} · 이
                        버전이 계약 기준으로 보존됩니다.
                      </p>
                    )}
                    {wid &&
                      canAccept &&
                      !q.accepted_at &&
                      i.status !== 'contracted' &&
                      index === i.quotes.length - 1 && (
                        <ActionForm
                          title={`견적 v${q.seq} 확인`}
                          label="이 견적으로 계약 확정·프로젝트 만들기"
                          onSubmit={async (d) => {
                            if (!d.has('confirm'))
                              throw new Error('조건 확인이 필요합니다')
                            await cs('POST', `/quotes/${q.id}/accept`)
                          }}
                        >
                          <label className="checkbox">
                            <input type="checkbox" name="confirm" required />
                            업무·금액·일정·지급·사용 권한을 확인했고, 이 버전의
                            제안을 수락합니다.
                          </label>
                          <p className="field-hint">
                            전자서명·자동 결제는 제공하지 않습니다. 프리랜서의
                            제안과 클라이언트의 수락을 같은 버전에 기록합니다.
                          </p>
                        </ActionForm>
                      )}
                  </details>
                ))}
                {!wid && i.status !== 'contracted' && <QuoteForm inquiry={i} />}
                {wid && !canAccept && i.status === 'quoted' && (
                  <p>
                    견적 확정은 의뢰를 작성한 소유자·관리자에게 요청해 주세요.
                  </p>
                )}
                {i.project_id && (
                  <Link
                    className="btn btn-primary"
                    to={
                      wid
                        ? `/client/projects/${i.project_id}`
                        : `/projects/${i.project_id}`
                    }
                  >
                    확정된 프로젝트 열기
                  </Link>
                )}
              </>
            )}
          </section>
        ))}
      </div>
    </>
  )
}
function QuoteForm({ inquiry }: { inquiry: Inquiry }) {
  const q = inquiry.quotes.at(-1)?.payload
  return (
    <ActionForm
      title="견적 제안 (제안 버전은 보존됩니다)"
      label="새 견적 버전 제안"
      onSubmit={(d) =>
        cs('POST', `/inquiries/${inquiry.id}/quotes`, {
          amount: str(d, 'amount'),
          vat: str(d, 'vat'),
          scope: str(d, 'scope'),
          deliverables: str(d, 'deliverables'),
          exclusions: str(d, 'exclusions'),
          revisions: Number(str(d, 'revisions')),
          due_date: str(d, 'due_date'),
          client_due_date: str(d, 'client_due_date'),
          payment: str(d, 'payment'),
          rights: str(d, 'rights'),
          originals: str(d, 'originals'),
        })
      }
    >
      <div className="cs-form-grid">
        <Input
          label="견적 금액 (원)"
          name="amount"
          type="number"
          min="0"
          value={q?.amount}
          required
        />
        <Select
          label="부가세"
          name="vat"
          value={q?.vat}
          options={[
            ['excluded', '부가세 별도'],
            ['included', '부가세 포함'],
            ['not_applicable', '해당 없음'],
          ]}
        />
        <Input
          label="포함 수정 횟수"
          name="revisions"
          type="number"
          min="0"
          max="99"
          value={q?.revisions ?? 2}
          required
        />
        <Input
          label="자료 제공 기한"
          name="client_due_date"
          type="date"
          value={q?.client_due_date}
          required
        />
        <Input
          label="납품일"
          name="due_date"
          type="date"
          value={q?.due_date ?? inquiry.payload.due_date ?? ''}
          required
        />
      </div>
      <Area
        label="작업 범위"
        name="scope"
        value={q?.scope ?? inquiry.payload.scope}
        required
      />
      <Area
        label="결과물·수량·파일 형식"
        name="deliverables"
        value={q?.deliverables ?? inquiry.payload.deliverables}
        required
      />
      <Area
        label="제외 항목·추가 작업 비용 기준"
        name="exclusions"
        value={q?.exclusions}
        required
      />
      <Area label="지급 시점·조건" name="payment" value={q?.payment} required />
      <Area label="사용 권한" name="rights" value={q?.rights} required />
      <Area
        label="원본 제공 조건"
        name="originals"
        value={q?.originals}
        required
      />
    </ActionForm>
  )
}
export function FreelancerInquiriesPage() {
  return (
    <div className="cs-shell">
      <p className="cs-eyebrow">CLIENT REQUESTS</p>
      <InquiriesView />
    </div>
  )
}
