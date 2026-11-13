"""쿠키 인증용 CSRF 방어: SameSite=Lax 쿠키 + 상태 변경 요청의 Origin 검사.

브라우저는 교차 출처 POST에 항상 Origin을 붙인다. 다음 중 하나면 통과시킨다.
- 같은 출처: Origin의 host:port가 요청의 Host 헤더와 같다
  (프론트 개발 서버가 Host를 그대로 넘기므로 localhost든 LAN IP든 같은 주소로 접속하면 맞는다)
- 허용 목록(FH_ALLOWED_ORIGINS)에 있는 Origin
Origin·Referer가 모두 없는 요청(서버 간 호출, 테스트 도구)은 쿠키를 자동으로 싣는
브라우저 요청이 아니므로 통과시킨다.
"""

from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.errors import error_body

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def is_allowed_origin(source: str, host: str | None) -> bool:
    if source in get_settings().allowed_origins:
        return True
    netloc = urlsplit(source).netloc.lower()
    return bool(host) and netloc == (host or "").lower()


class OriginCheckMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            source = origin or (_origin_of(referer) if referer else None)
            if source is not None and not is_allowed_origin(source, request.headers.get("host")):
                return JSONResponse(
                    error_body("csrf_rejected", "request origin is not allowed"), status_code=403
                )
        return await call_next(request)
