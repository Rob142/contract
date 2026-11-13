import { Link } from 'react-router'

export function NotFoundPage() {
  return (
    <div className="center-screen">
      <div>
        <p className="page-title">페이지를 찾을 수 없어요</p>
        <p className="page-desc">주소가 바뀌었거나 접근할 수 없는 페이지예요.</p>
        <p>
          <Link to="/dashboard" className="link-strong">
            대시보드로 가기
          </Link>
        </p>
      </div>
    </div>
  )
}
