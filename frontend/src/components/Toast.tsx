import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { onContractDone, type ContractDoneEvent } from '../lib/contractEvents'

interface Toast {
  id: number
  text: string
  link: string
  tone: 'ok' | 'warning'
}

const EVENT_TEXT: Record<ContractDoneEvent['kind'], { text: (title: string) => string; link: (id: string) => string; tone: Toast['tone'] }> = {
  extracted: {
    text: (t) => `«${t}» 텍스트 추출이 끝났어요. 조건을 확인해 주세요.`,
    link: (id) => `/contracts/${id}`,
    tone: 'ok',
  },
  analyzed: {
    text: (t) => `«${t}» 분석이 끝났어요. 결과를 확인해 보세요.`,
    link: (id) => `/contracts/${id}/analysis`,
    tone: 'ok',
  },
  failed: {
    text: (t) => `«${t}» 텍스트 추출에 실패했어요.`,
    link: (id) => `/contracts/${id}`,
    tone: 'warning',
  },
  analyze_failed: {
    text: (t) => `«${t}» 분석을 마치지 못했어요.`,
    link: (id) => `/contracts/${id}`,
    tone: 'warning',
  },
}

/** 처리 완료 알림. 다른 화면을 보고 있어도 기다린 결과가 끝나면 알려준다 (5초 뒤 사라짐). */
export function ContractToast() {
  const [toasts, setToasts] = useState<Toast[]>([])

  useEffect(() => {
    let seq = 0
    const timers = new Map<number, ReturnType<typeof setTimeout>>()
    const dismiss = (id: number) =>
      setToasts((ts) => {
        const timer = timers.get(id)
        if (timer) {
          clearTimeout(timer)
          timers.delete(id)
        }
        return ts.filter((t) => t.id !== id)
      })

    const off = onContractDone((event) => {
      const spec = EVENT_TEXT[event.kind]
      const id = ++seq
      setToasts((ts) => [...ts.slice(-2), { id, text: spec.text(event.title), link: spec.link(event.contractId), tone: spec.tone }])
      timers.set(id, setTimeout(() => dismiss(id), 5000))
    })
    return () => {
      off()
      for (const timer of timers.values()) clearTimeout(timer)
    }
  }, [])

  if (toasts.length === 0) return null
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={t.tone === 'warning' ? 'toast toast-warning' : 'toast'}>
          <span>{t.text}</span>
          <span className="toast-actions">
            <Link to={t.link} onClick={() => setToasts((ts) => ts.filter((x) => x.id !== t.id))}>
              보기 →
            </Link>
            <button type="button" className="toast-close" aria-label="알림 닫기" onClick={() => setToasts((ts) => ts.filter((x) => x.id !== t.id))}>
              ×
            </button>
          </span>
        </div>
      ))}
    </div>
  )
}
