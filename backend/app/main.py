from fastapi import FastAPI

from app.api.router import api_router
from app.core.csrf import OriginCheckMiddleware
from app.core.errors import register_error_handlers
from app.core.logging import RequestIdMiddleware, configure_logging


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Freelance Hub API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    # 나중에 추가한 미들웨어가 바깥쪽: 요청 ID → Origin 검사 → 라우트
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
