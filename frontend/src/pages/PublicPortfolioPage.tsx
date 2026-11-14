import { useParams } from 'react-router'

import { usePublicPortfolio } from '../api/sharing'
import { Loading } from '../components/ui'
import { useNoIndex } from '../lib/useNoIndex'
import { JOB_TYPE_LABELS, formatFullDate } from '../lib/format'

/** 로그인 없이 보는 공개 포트폴리오 카드 (/p/:slug) */
export function PublicPortfolioPage() {
  const { slug = '' } = useParams()
  useNoIndex()
  const card = usePublicPortfolio(slug)

  if (card.isPending) return <Loading />
  if (card.isError) {
    return (
      <main className="app-main client-page">
        <div className="card">
          <h1 className="page-title">볼 수 없는 포트폴리오예요</h1>
          <p className="muted">비공개로 바뀌었거나 주소가 올바르지 않아요.</p>
        </div>
      </main>
    )
  }
  const c = card.data
  return (
    <main className="app-main client-page">
      <div className="page-head">
        <div>
          <p className="page-eyebrow">
            {c.freelancer_name} · {JOB_TYPE_LABELS[c.job_type]}
          </p>
          <h1 className="page-title">{c.title}</h1>
          <p className="page-desc">
            {c.period_start ? formatFullDate(c.period_start) : ''} {c.period_start || c.period_end ? '~' : ''}{' '}
            {c.period_end ? formatFullDate(c.period_end) : ''}
            {c.client_name ? ` · ${c.client_name}` : ''}
          </p>
        </div>
      </div>
      {c.description && (
        <section className="card">
          <p style={{ whiteSpace: 'pre-wrap' }}>{c.description}</p>
        </section>
      )}
      {c.assets.length > 0 && (
        <section className="card" aria-labelledby="assets-title">
          <h2 id="assets-title" className="card-title">
            결과물
          </h2>
          <ul className="row-list">
            {c.assets.map((a) => (
              <li key={a.attachment_id}>
                {a.url ? (
                  <a href={a.url} target="_blank" rel="noopener noreferrer">
                    {a.title}
                  </a>
                ) : (
                  <a href={`/api/v1/public/portfolio/${slug}/assets/${a.attachment_id}/file`}>{a.title}</a>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      {c.quotes.length > 0 && (
        <section className="card" aria-labelledby="quotes-title">
          <h2 id="quotes-title" className="card-title">
            클라이언트 한마디
          </h2>
          {c.quotes.map((q) => (
            <blockquote key={q.quote}>
              &ldquo;{q.quote}&rdquo; <span className="muted small">— {q.author}</span>
            </blockquote>
          ))}
        </section>
      )}
    </main>
  )
}
