/** 계약서 처리 상태 전환을 감지해 앱에 알린다 (처리 완료 토스트용, UX 문서 4장 D).

폴링으로 읽은 목록·상세 데이터를 이전 값과 비교해 "기다리던 처리가 끝났다"는 전환만 골라
구독자에게 전달한다. 이전 상태는 모듈 단위로 유지해 화면을 이동해도 잊지 않는다.
 */

export type ContractDoneKind = 'extracted' | 'analyzed' | 'failed' | 'analyze_failed'

export interface ContractDoneEvent {
  contractId: string
  title: string
  kind: ContractDoneKind
}

type Listener = (event: ContractDoneEvent) => void

const listeners = new Set<Listener>()
const prevStatus = new Map<string, string>()

export function onContractDone(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

function emit(event: ContractDoneEvent) {
  for (const listener of listeners) listener(event)
}

/** 상태 하나짜리 목록·상세 데이터를 넣으면 전환을 감지한다 */
export function detectContractTransitions(items: Array<{ id: string; title: string; status: string }>) {
  for (const c of items) {
    const before = prevStatus.get(c.id)
    prevStatus.set(c.id, c.status)
    if (before === undefined || before === c.status) continue
    if (before === 'uploaded' || before === 'extracting') {
      if (c.status === 'needs_review') emit({ contractId: c.id, title: c.title, kind: 'extracted' })
      else if (c.status === 'failed') emit({ contractId: c.id, title: c.title, kind: 'failed' })
    } else if (before === 'analyzing') {
      if (c.status === 'analyzed') emit({ contractId: c.id, title: c.title, kind: 'analyzed' })
      else if (c.status === 'ready') emit({ contractId: c.id, title: c.title, kind: 'analyze_failed' })
    }
  }
}
