/**
 * 프로젝트 화면에서 "계약서 연결"로 출발한 계약서가 어느 프로젝트로 가야 하는지 기억한다.
 * 조건 확인 중에 다른 메뉴로 나갔다 와도 잊지 않게 하려는 이 브라우저만의 편의 기능이라,
 * 저장소를 못 쓰면 주소의 ?project= 만으로 동작한다.
 */
const key = (contractId: string) => `fh.linkTarget.${contractId}`

export function rememberLinkTarget(contractId: string, projectId: string) {
  try {
    localStorage.setItem(key(contractId), projectId)
  } catch {
    // 기억하지 못해도 동작에는 영향 없음
  }
}

export function recallLinkTarget(contractId: string): string | null {
  try {
    return localStorage.getItem(key(contractId))
  } catch {
    return null
  }
}

export function forgetLinkTarget(contractId: string) {
  try {
    localStorage.removeItem(key(contractId))
  } catch {
    // 무시
  }
}
