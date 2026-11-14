import { useEffect } from 'react'

/** 토큰이 주소에 있는 페이지는 검색엔진에 노출하지 않는다 */
export function useNoIndex(): void {
  useEffect(() => {
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex, nofollow'
    document.head.appendChild(meta)
    return () => meta.remove()
  }, [])
}
