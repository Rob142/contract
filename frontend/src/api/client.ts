/** /api/v1 호출. 세션은 HttpOnly 쿠키로 자동 전송된다. 금액은 십진 문자열로 주고받는다. */

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

type Method = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'

interface RequestOptions {
  headers?: Record<string, string>
  signal?: AbortSignal
}

export async function api<T>(method: Method, path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api/v1${path}`, {
      method,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: options.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'network_error', 'network request failed')
  }

  if (res.status === 204) return undefined as T

  const data: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const error = (data as { error?: { code?: string; message?: string; details?: unknown } } | null)?.error
    throw new ApiError(res.status, error?.code ?? 'http_error', error?.message ?? res.statusText, error?.details)
  }
  return data as T
}

/** 422 validation_error의 details를 {필드명: 메시지}로 바꾼다. */
export function fieldErrorsOf(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.code !== 'validation_error' || !Array.isArray(error.details)) {
    return {}
  }
  const result: Record<string, string> = {}
  for (const item of error.details as { loc?: unknown[]; msg?: string }[]) {
    const field = item.loc?.at(-1)
    if (typeof field === 'string' && !(field in result)) result[field] = item.msg ?? 'invalid'
  }
  return result
}
