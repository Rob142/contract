import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist/legacy/build/pdf.mjs'
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'
import { useEffect, useRef, useState } from 'react'

GlobalWorkerOptions.workerSrc = workerUrl

export interface Highlight {
  page: number
  /** PDF 포인트, 왼쪽 위 원점 (추출 블록의 bbox) */
  bbox: { x0: number; top: number; x1: number; bottom: number }
}

interface PdfViewerProps {
  url: string
  page: number
  onPageChange: (page: number) => void
  highlight?: Highlight | null
}

const ZOOM_STEPS = [0.75, 1, 1.25, 1.5, 2]

/** 원본 PDF 보기. 화면 폭에 맞춘 크기를 100%로 두고, 근거 위치를 노란 상자로 표시한다. */
export function PdfViewer({ url, page, onPageChange, highlight }: PdfViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const frameRef = useRef<HTMLDivElement>(null)
  const highlightRef = useRef<HTMLDivElement>(null)
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null)
  const [error, setError] = useState(false)
  const [zoomIndex, setZoomIndex] = useState(1)
  const [scale, setScale] = useState(1)
  const [frameWidth, setFrameWidth] = useState(0)

  // 문서 열기 (같은 출처라 세션 쿠키가 함께 간다)
  useEffect(() => {
    let cancelled = false
    const task = getDocument({ url, withCredentials: true })
    task.promise.then(
      (loaded) => !cancelled && setDoc(loaded),
      () => !cancelled && setError(true),
    )
    return () => {
      cancelled = true
      void task.destroy()
    }
  }, [url])

  // 화면 폭 변화 추적
  useEffect(() => {
    const frame = frameRef.current
    if (!frame) return
    const observer = new ResizeObserver(([entry]) => setFrameWidth(entry?.contentRect.width ?? 0))
    observer.observe(frame)
    return () => observer.disconnect()
  }, [])

  // 페이지 그리기
  useEffect(() => {
    if (!doc || !canvasRef.current || frameWidth === 0) return
    let renderTask: RenderTask | null = null
    let cancelled = false
    void doc.getPage(Math.min(Math.max(page, 1), doc.numPages)).then((pdfPage) => {
      if (cancelled || !canvasRef.current) return
      const base = pdfPage.getViewport({ scale: 1 })
      const fitScale = (frameWidth - 48) / base.width
      const nextScale = Math.max(fitScale, 0.3) * (ZOOM_STEPS[zoomIndex] ?? 1)
      const viewport = pdfPage.getViewport({ scale: nextScale })
      const ratio = window.devicePixelRatio || 1
      const canvas = canvasRef.current
      canvas.width = Math.floor(viewport.width * ratio)
      canvas.height = Math.floor(viewport.height * ratio)
      canvas.style.width = `${Math.floor(viewport.width)}px`
      canvas.style.height = `${Math.floor(viewport.height)}px`
      setScale(nextScale)
      renderTask = pdfPage.render({
        canvas,
        viewport,
        transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
      })
      renderTask.promise.catch(() => undefined)
    })
    return () => {
      cancelled = true
      renderTask?.cancel()
    }
  }, [doc, page, zoomIndex, frameWidth])

  // 근거 위치로 스크롤
  useEffect(() => {
    if (highlight && highlight.page === page) {
      highlightRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
  }, [highlight, page, scale])

  const total = doc?.numPages ?? 0
  const box = highlight && highlight.page === page ? highlight.bbox : null

  return (
    <div className="pdf-viewer">
      <div className="pdf-toolbar">
        <span className="muted">원본 PDF</span>
        <div className="pdf-controls">
          <button type="button" className="icon-button" aria-label="이전 페이지" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
            ‹
          </button>
          <span className="small" aria-live="polite">
            {total ? `${page} / ${total} 페이지` : '불러오는 중'}
          </span>
          <button type="button" className="icon-button" aria-label="다음 페이지" disabled={page >= total} onClick={() => onPageChange(page + 1)}>
            ›
          </button>
          <button type="button" className="icon-button" aria-label="축소" disabled={zoomIndex === 0} onClick={() => setZoomIndex((z) => z - 1)}>
            −
          </button>
          <span className="small">{Math.round((ZOOM_STEPS[zoomIndex] ?? 1) * 100)}%</span>
          <button
            type="button"
            className="icon-button"
            aria-label="확대"
            disabled={zoomIndex === ZOOM_STEPS.length - 1}
            onClick={() => setZoomIndex((z) => z + 1)}
          >
            +
          </button>
        </div>
      </div>
      <div className="pdf-frame" ref={frameRef}>
        {error ? (
          <p className="center-block">PDF를 표시할 수 없어요. 원본을 내려받아 확인해 주세요.</p>
        ) : (
          <div className="pdf-page">
            <canvas ref={canvasRef} aria-label={`원본 ${page}페이지`} role="img" />
            {box && (
              <div
                ref={highlightRef}
                className="pdf-highlight"
                style={{
                  left: box.x0 * scale - 4,
                  top: box.top * scale - 3,
                  width: (box.x1 - box.x0) * scale + 8,
                  height: (box.bottom - box.top) * scale + 6,
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
