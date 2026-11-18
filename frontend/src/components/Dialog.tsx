import { useEffect, useRef, type ReactNode } from 'react'

interface DialogProps {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  wide?: boolean
}

/** 네이티브 <dialog> 모달: 포커스 가두기·Esc 닫기·배경 비활성화를 브라우저가 처리한다. */
export function Dialog({ open, onClose, title, children, footer, wide }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const pressedOnBackdrop = useRef(false)

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      className={wide ? 'dialog dialog-wide' : 'dialog'}
      aria-labelledby="dialog-title"
      onClose={onClose}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onPointerDown={(e) => {
        pressedOnBackdrop.current = e.target === ref.current
      }}
      onClick={(e) => {
        // 바깥(배경) 클릭으로 닫기. 누른 곳과 뗀 곳이 모두 배경일 때만 닫는다
        // (창 안에서 글자를 드래그하다 바깥에서 손을 떼도 닫히지 않게)
        const fromBackdrop = pressedOnBackdrop.current
        pressedOnBackdrop.current = false
        if (fromBackdrop && e.target === ref.current) onClose()
      }}
    >
      {open && (
        <div className="dialog-body">
          <div className="dialog-head">
            <h2 id="dialog-title">{title}</h2>
            <button type="button" className="icon-button" aria-label="닫기" onClick={onClose}>
              ×
            </button>
          </div>
          {children}
          {footer && <div className="dialog-foot">{footer}</div>}
        </div>
      )}
    </dialog>
  )
}
