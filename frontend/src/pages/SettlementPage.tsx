import { useState } from 'react'
import { Link } from 'react-router'

import { useMonthDetail, useMonthlyIncome, useEvidence } from '../api/sharing'
import { EmptyState, LoadError, Loading } from '../components/ui'
import { formatFullDate, formatWon } from '../lib/format'

const DOC_LABEL: Record<string, string> = {
  tax_invoice: '세금계산서',
  cash_receipt: '현금영수증',
  receipt: '영수증',
  contract_copy: '계약서 사본',
  other: '기타',
}

function MonthlyIncomeCard() {
  const income = useMonthlyIncome(12)
  const [open, setOpen] = useState<string | null>(null)
  const detail = useMonthDetail(open)

  if (income.isPending) return <Loading />
  if (income.isError) return <LoadError error={income.error} onRetry={() => void income.refetch()} />
  const { months, received_total } = income.data
  const max = Math.max(...months.map((m) => Number(m.received)), 1)

  return (
    <section className="card" aria-labelledby="income-title">
      <div className="card-head">
        <h2 id="income-title" className="card-title">
          월별 수입
        </h2>
        <span className="muted small">입금일 기준 · 최근 12개월 합계 {formatWon(received_total)}</span>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>월</th>
              <th>수입(입금액)</th>
              <th aria-label="막대" style={{ width: '40%' }} />
              <th>발행 청구액</th>
            </tr>
          </thead>
          <tbody>
            {[...months].reverse().map((m) => (
              <tr key={m.month}>
                <td>
                  {m.received === '0' ? (
                    <span className="plain-month">{m.month}</span>
                  ) : (
                    <button
                      type="button"
                      className="link-button"
                      aria-expanded={open === m.month}
                      onClick={() => setOpen(open === m.month ? null : m.month)}
                    >
                      {m.month}
                    </button>
                  )}
                </td>
                <td>{formatWon(m.received)}</td>
                <td>
                  <div className="income-bar" role="img" aria-label={`${m.month} 수입 ${formatWon(m.received)}`}>
                    <span style={{ width: `${(Number(m.received) / max) * 100}%` }} />
                  </div>
                </td>
                <td className="muted">{formatWon(m.billed)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && detail.data && (
        <div className="notice">
          <strong>{open} 입금 내역</strong>
          <ul className="row-list">
            {detail.data.projects.map((p) => (
              <li key={p.project_id}>
                <Link to={`/projects/${p.project_id}`}>{p.name}</Link> · {formatWon(p.received)}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="muted small">수입은 실제로 입금을 확인한 날짜 기준이에요. 취소한 입금과 초안 인보이스는 빠져요.</p>
    </section>
  )
}

function EvidenceCard() {
  const evidence = useEvidence()
  return (
    <section className="card" aria-labelledby="evidence-title">
      <div className="card-head">
        <h2 id="evidence-title" className="card-title">
          증빙 자료
        </h2>
        <Link to="/projects" className="link-strong">
          프로젝트에서 올리기 →
        </Link>
      </div>
      {evidence.isPending ? (
        <Loading />
      ) : !evidence.data?.length ? (
        <EmptyState title="올린 증빙이 없어요.">프로젝트 상세의 &lsquo;결과물·증빙&rsquo;에서 종류를 증빙으로 골라 올려 주세요.</EmptyState>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>자료</th>
                <th>종류</th>
                <th>프로젝트</th>
                <th>발행일</th>
                <th>금액</th>
              </tr>
            </thead>
            <tbody>
              {evidence.data.map((e) => (
                <tr key={e.id}>
                  <td>
                    {e.url ? (
                      <a href={e.url} target="_blank" rel="noopener noreferrer">
                        {e.title}
                      </a>
                    ) : (
                      <a href={`/api/v1/attachments/${e.id}/file?download=true`}>{e.title}</a>
                    )}
                  </td>
                  <td>{e.doc_type ? DOC_LABEL[e.doc_type] : '-'}</td>
                  <td>
                    <Link to={`/projects/${e.project_id}`}>{e.project_name}</Link>
                  </td>
                  <td>{e.issued_on ? formatFullDate(e.issued_on) : '-'}</td>
                  <td>{e.amount ? formatWon(e.amount) : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted small">
        세금계산서·현금영수증은 국세청(홈택스) 등 외부 시스템에서 발행해요. 여기서는 받은 자료를 올려 정리만 해요.
      </p>
    </section>
  )
}

export function SettlementPage() {
  return (
    <>
      <div className="page-head">
        <div>
          <p className="page-eyebrow">나의 워크스페이스</p>
          <h1 className="page-title">서류·정산</h1>
          <p className="page-desc">월별 수입과 증빙 자료를 한곳에서 확인해요. 인보이스는 인보이스 메뉴에서 관리해요.</p>
        </div>
        <div className="head-actions">
          <Link to="/invoices" className="btn btn-secondary">
            인보이스 목록
          </Link>
        </div>
      </div>
      <div className="stack">
        <MonthlyIncomeCard />
        <EvidenceCard />
      </div>
    </>
  )
}
