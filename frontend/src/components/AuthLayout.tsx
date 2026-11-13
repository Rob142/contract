import { Link, Outlet } from 'react-router'

import { LockIcon } from './icons'

/** 01 로그인 · 02 회원가입 공통 레이아웃. 태블릿 이하에서는 왼쪽 소개 영역을 숨긴다. */
export function AuthLayout() {
  return (
    <div className="auth">
      <aside className="auth-hero">
        <Link to="/login" className="logo">
          Freelance Hub
        </Link>

        <div className="auth-hero-body">
          <p className="auth-eyebrow">프리랜서의 일을 하나로</p>
          <h2 className="auth-headline">
            계약부터 입금까지,
            <br />내 일의 흐름을
            <br />
            한곳에서.
          </h2>
          <p className="auth-lead">
            계약을 확인하고, 작업을 관리하고,
            <br />
            놓친 청구 없이 프로젝트를 마무리하세요.
          </p>

          {/* 서비스 흐름을 보여주는 예시 카드 (실제 데이터 아님) */}
          <div className="flow-card" aria-hidden="true">
            <div className="flow-card-head">
              <div>
                <p className="flow-card-title">모노 스튜디오 브랜드 디자인</p>
                <p className="flow-card-sub">계약 검토부터 최종 청구까지</p>
              </div>
              <span className="badge badge-green">진행 중</span>
            </div>
            <ol className="flow-steps">
              <li>계약 확인</li>
              <li>→</li>
              <li>작업 완료</li>
              <li>→</li>
              <li className="is-current">입금 확인</li>
            </ol>
            <div className="progress">
              <span style={{ width: '66%' }} />
            </div>
          </div>
        </div>

        <p className="auth-footnote">프리랜서 개인을 위한 비공개 워크스페이스</p>
      </aside>

      <main className="auth-main">
        <div className="auth-panel">
          <Link to="/login" className="logo auth-mobile-logo">
            Freelance Hub
          </Link>
          <Outlet />
          <p className="auth-privacy">
            <LockIcon size={16} />
            외부 업체의 가입 없이 혼자 사용할 수 있어요.
          </p>
        </div>
      </main>
    </div>
  )
}
