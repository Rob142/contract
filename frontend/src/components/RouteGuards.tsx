import { Navigate, useLocation, useSearchParams } from 'react-router'

import { useMe } from '../api/auth'
import { messageOf } from '../api/messages'
import { safeNextPath } from '../lib/format'
import { AppLayout } from './AppLayout'
import { AuthLayout } from './AuthLayout'

function FullScreenLoading() {
  return (
    <div className="center-screen" role="status">
      <div className="spinner" />
      <span className="visually-hidden">불러오는 중</span>
    </div>
  )
}

function FullScreenError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="center-screen">
      <div>
        <p>{messageOf(error)}</p>
        <button type="button" className="btn btn-secondary" onClick={onRetry}>
          다시 시도
        </button>
      </div>
    </div>
  )
}

/** 로그인한 사용자만. 아니면 로그인 화면으로 보내고, 로그인 후 원래 위치로 돌아온다. */
export function RequireAuth() {
  const me = useMe()
  const location = useLocation()

  if (me.isPending) return <FullScreenLoading />
  if (me.isError) return <FullScreenError error={me.error} onRetry={() => void me.refetch()} />
  if (!me.data) {
    const next = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?next=${next}`} replace />
  }
  return <AppLayout user={me.data} />
}

/** 로그인 전에만. 로그인하면(또는 이미 로그인했으면) ?next 위치나 대시보드로 보낸다. */
export function GuestOnly() {
  const me = useMe()
  const [searchParams] = useSearchParams()

  if (me.isPending) return <FullScreenLoading />
  if (me.data)
    return (
      <Navigate
        to={safeNextPath(searchParams.get('next'), me.data.preferred_mode === 'client' ? '/client' : '/dashboard')}
        replace
      />
    )
  return <AuthLayout />
}

/** Entry point honors the saved UI preference; authorization stays on the server. */
export function EntryPage() {
  const me = useMe()
  return <Navigate to={me.data?.preferred_mode === 'client' ? '/client' : '/dashboard'} replace />
}
