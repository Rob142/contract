import { Link, useSearchParams } from 'react-router'

import { useInvoices, type InvoiceGroup } from '../api/invoices'
import { EmptyState, FilterTabs, LoadError, Loading } from '../components/ui'
import { formatShortDate, formatWon, todayIso } from '../lib/format'
import { invoiceBadge } from '../lib/invoiceStatus'

type Filter = InvoiceGroup | 'all'
const FILTERS: Filter[] = ['all', 'outstanding', 'draft', 'unpaid', 'partial', 'paid', 'overdue', 'cancelled']
const FILTER_LABELS: Record<Filter, string> = {
  all: '전체',
  draft: '초안',
  unpaid: '미입금',
  partial: '일부 입금',
  paid: '완납',
  overdue: '연체',
  outstanding: '미수',
  cancelled: '취소',
}

function monthOptions(): { value: string; label: string }[] {
  const [y = 0, m = 1] = todayIso().split('-').map(Number)
  const prev = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`
  return [
    { value: '', label: '전체 기간' },
    { value: `${y}-${String(m).padStart(2, '0')}`, label: '이번 달' },
    { value: prev, label: '지난 달' },
  ]
}

function Kpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="card kpi">
      <p className="kpi-label">{label}</p>
      <p className="kpi-value">{value}</p>
      <p className="kpi-sub">{sub}</p>
    </div>
  )
}

/** 10 인보이스 목록 */
export function InvoicesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const filter = (FILTERS.find((f) => f === searchParams.get('group')) ?? 'all') as Filter
  const month = searchParams.get('month') ?? ''
  const projectId = searchParams.get('project') ?? ''
  const invoices = useInvoices(filter, month, projectId)
  const projectName = projectId ? invoices.data?.items[0]?.project_name : undefined

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    setSearchParams(next, { replace: true })
  }

  const counts = invoices.data?.counts
  const k = invoices.data?.kpis
  // 연체·취소는 있을 때만, 미수(미입금+일부 입금)는 KPI에서 들어왔을 때만 탭으로 보인다
  const tabs = FILTERS.filter(
    (f) => (f === 'outstanding' ? filter === 'outstanding' : !['overdue', 'cancelled'].includes(f) || (counts?.[f] ?? 0) > 0),
  ).map((f) => ({
    value: f,
    label: FILTER_LABELS[f],
    count: counts?.[f],
  }))

  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">나의 워크스페이스</p>
          <h1 className="page-title">인보이스</h1>
          <p className="page-desc">발행한 청구와 입금 기록을 확인하고 미수액을 관리하세요.</p>
        </div>
        <Link to={projectId ? `/invoices/new?project=${projectId}` : '/invoices/new'} className="btn btn-primary">
          + 인보이스 작성
        </Link>
      </div>

      <div className="kpi-grid">
        <Kpi label="이번 달 청구액" value={k ? formatWon(k.billed_this_month) : '—'} sub="발행된 인보이스 기준" />
        <Kpi label="누적 입금액" value={k ? formatWon(k.paid_total) : '—'} sub="직접 확인한 입금 기록" />
        <Kpi label="미수액" value={k ? formatWon(k.outstanding_total) : '—'} sub="청구액 − 유효 입금액" />
        <Kpi
          label="지급 기한 경과"
          value={k ? `${k.overdue_count}건` : '—'}
          sub={k && k.overdue_count > 0 ? `잔액 ${formatWon(k.overdue_balance)}` : '기한이 지난 청구가 없어요'}
        />
      </div>

      <div className="tabs-row">
        <FilterTabs label="입금 상태" items={tabs} value={filter} onChange={(v) => setParam('group', v === 'all' ? '' : v)} />
        {projectId && (
          <span className="filter-chip">
            프로젝트: {projectName ?? '선택됨'}
            <button type="button" aria-label="프로젝트 필터 해제" onClick={() => setParam('project', '')}>
              ×
            </button>
          </span>
        )}
        <select className="input month-select" aria-label="기간" value={month} onChange={(e) => setParam('month', e.target.value)}>
          {monthOptions().map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      <section className="card" aria-labelledby="invoice-list-title">
        <h2 id="invoice-list-title" className="card-title">
          청구 내역
        </h2>
        {invoices.isPending ? (
          <Loading />
        ) : invoices.isError ? (
          <LoadError error={invoices.error} onRetry={() => void invoices.refetch()} />
        ) : invoices.data.items.length === 0 ? (
          <EmptyState title={filter === 'all' && !month ? '아직 작성한 인보이스가 없어요.' : '해당하는 인보이스가 없어요.'}>
            {filter === 'all' && !month && (
              <Link to="/invoices/new" className="btn btn-secondary">
                인보이스 작성하기
              </Link>
            )}
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table table-links">
              <thead>
                <tr>
                  <th>인보이스와 프로젝트</th>
                  <th className="num">청구 금액</th>
                  <th className="num">입금 금액</th>
                  <th>지급 기한</th>
                  <th>입금 상태</th>
                </tr>
              </thead>
              <tbody>
                {invoices.data.items.map((inv) => {
                  const badge = invoiceBadge(inv)
                  return (
                    <tr key={inv.id}>
                      <td>
                        <Link to={`/invoices/${inv.id}`} className="row-link">
                          {inv.invoice_no ?? '작성 중'} · {inv.title}
                        </Link>
                        <span className="muted small">
                          {' · '}
                          <Link to={`/projects/${inv.project_id}`} className="muted-link">
                            {inv.project_name}
                          </Link>
                        </span>
                      </td>
                      <td className="num">{formatWon(inv.total)}</td>
                      <td className="num">{inv.status === 'draft' ? '—' : formatWon(inv.paid_amount)}</td>
                      <td>{inv.due_date ? formatShortDate(inv.due_date) : '미정'}</td>
                      <td>
                        <span className={badge.className}>{badge.label}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted small" style={{ margin: '16px 0 0' }}>
          초안 금액은 청구액과 미수액 합계에 포함되지 않습니다.
        </p>
      </section>

      <div className="grid-2" style={{ marginTop: 24 }}>
        <section className="card">
          <h2 className="card-title">입금은 직접 확인해 주세요</h2>
          <p className="muted" style={{ margin: 0, lineHeight: 1.8 }}>
            실제 입금을 확인한 뒤 금액과 날짜를 기록하면 입금 상태와 미수액이 함께 갱신됩니다. 은행과 연동하지 않아요.
          </p>
        </section>
        <section className="card">
          <h2 className="card-title">문서를 PDF로 보관하세요</h2>
          <p className="muted" style={{ margin: 0, lineHeight: 1.8 }}>
            발행 인보이스와 입금 기록마다 만든 입금확인서를 언제든 내려받을 수 있어요. 세금계산서·법정 현금영수증은 아니에요.
          </p>
        </section>
      </div>
    </>
  )
}
