import type { TaskStatus } from '../api/projects'

export type DropTarget = { status: TaskStatus; index: number }

/** 카드 앞·뒤와 열의 빈 공간에 놓는 경우를 같은 규칙으로 처리한다. */
export function dropIndex(ids: string[], overId: string | undefined, after: boolean): number {
  const index = overId ? ids.indexOf(overId) : -1
  return index < 0 ? ids.length : index + (after ? 1 : 0)
}
