"""공통 오류 형식: {"error": {"code", "message", "details"}}

422 입력 오류 · 401 미인증 · 403/404 접근 불가 · 409 충돌·중복 (설계서 8장)
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def not_found(what: str = "resource") -> AppError:
    # 남의 리소스도 404로 응답해 존재 여부를 드러내지 않는다
    return AppError(404, "not_found", f"{what} not found")


def conflict(code: str, message: str, details: Any = None) -> AppError:
    return AppError(409, code, message, details)


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": jsonable_encoder(details)}}


# PostgreSQL SQLSTATE → API 오류 코드
_SQLSTATE_CODES = {
    "23505": ("duplicate", "the resource already exists"),
    "23503": ("reference_conflict", "the resource is referenced by or refers to missing data"),
    "23514": ("rule_violation", "the request violates a data rule"),
    "40001": ("retry_conflict", "a concurrent update conflicted; retry the request"),
    "40P01": ("retry_conflict", "a concurrent update conflicted; retry the request"),
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_error", "request validation failed", details), status_code=422
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(IntegrityError)
    async def handle_integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        code, message = _SQLSTATE_CODES.get(sqlstate or "", ("conflict", "the request conflicts with data"))
        diag = getattr(exc.orig, "diag", None)
        details = {"constraint": getattr(diag, "constraint_name", None)} if diag else None
        status = 409
        logger.info("integrity error sqlstate=%s code=%s", sqlstate, code)
        return JSONResponse(error_body(code, message, details), status_code=status)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse(error_body("internal_error", "unexpected server error"), status_code=500)
