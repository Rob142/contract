/**
 * 재전송 키 (Idempotency-Key). 같은 작업을 다시 보낼 때는 같은 키를 쓴다.
 * crypto.randomUUID는 HTTPS에서만 동작하므로 LAN(http) 접속에서도 되는 getRandomValues를 쓴다.
 */
export function newIdempotencyKey(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}
