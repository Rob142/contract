import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { useLogout, useUpdateMe, type User } from '../api/auth'
import { avatarInitial } from '../lib/format'
import { ContractToast } from './Toast'
import { BoardIcon, ChevronDownIcon, FileIcon, HomeIcon, LedgerIcon, PortfolioIcon, ReceiptIcon } from './icons'

const NAV_ITEMS = [
  { to: '/dashboard', label: '대시보드', Icon: HomeIcon },
  { to: '/contracts', label: '계약서', Icon: FileIcon },
  { to: '/projects', label: '프로젝트', Icon: BoardIcon },
  { to: '/invoices', label: '인보이스', Icon: ReceiptIcon },
  { to: '/settlement', label: '서류·정산', Icon: LedgerIcon },
  { to: '/portfolio', label: '포트폴리오', Icon: PortfolioIcon },
] as const

function UserMenu({ user }: { user: User }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const logout = useLogout()
  const navigate = useNavigate()
  const location = useLocation()

  // 화면 이동 시 닫기
  const [lastPath, setLastPath] = useState(location.pathname)
  if (lastPath !== location.pathname) {
    setLastPath(location.pathname)
    setOpen(false)
  }

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const handleLogout = () => {
    logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })
  }

  return (
    <div className="user-menu" ref={ref}>
      <button
        type="button"
        className="user-menu-button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="avatar">{avatarInitial(user.name)}</span>
        <span className="user-menu-name">{user.name}</span>
        <ChevronDownIcon size={18} />
      </button>
      {open && (
        <div className="user-menu-list" role="menu">
          <Link to="/settings" role="menuitem">
            내 정보와 설정
          </Link>
          <button type="button" role="menuitem" onClick={handleLogout} disabled={logout.isPending}>
            로그아웃
          </button>
        </div>
      )}
    </div>
  )
}

export function AppLayout({ user }: { user: User }) {
  const location = useLocation()
  const navigate = useNavigate()
  const update = useUpdateMe()
  const clientMode = location.pathname.startsWith('/client/') || location.pathname === '/client'
  return (
    <>
      <header className="app-header">
        <div className="app-header-inner">
          <Link to={clientMode ? '/client' : '/dashboard'} className="logo">
            Freelance Hub
          </Link>
          <nav className="top-nav" aria-label="주요 메뉴">
            {(clientMode ? [] : NAV_ITEMS).map(({ to, label }) => (
              <NavLink key={to} to={to}>
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="header-right">
            <button
              type="button"
              className="btn btn-secondary"
              disabled={update.isPending}
              onClick={() => {
                const mode = clientMode ? 'freelancer' : 'client'
                update.mutate(
                  { preferred_mode: mode },
                  { onSuccess: () => navigate(mode === 'client' ? '/client' : '/dashboard') },
                )
              }}
            >
              {clientMode ? '프리랜서로 전환' : '클라이언트로 전환'}
            </button>
            {!clientMode && (
              <Link to="/client-requests" className="workspace-label">
                받은 의뢰
              </Link>
            )}
            {!clientMode && (
              <Link to="/client-profile" className="workspace-label">
                공개 프로필
              </Link>
            )}
            <UserMenu user={user} />
          </div>
        </div>
      </header>

      <main className="app-main">
        <Outlet context={user} />
      </main>

      {/* 모바일 하단 탭바 (640px 미만에서만 표시) */}
      <nav className="bottom-tabs" aria-label="주요 메뉴">
        {(clientMode ? [] : NAV_ITEMS).map(({ to, label, Icon }) => (
          <NavLink key={to} to={to}>
            <Icon size={22} />
            {label}
          </NavLink>
        ))}
      </nav>

      <ContractToast />
    </>
  )
}
