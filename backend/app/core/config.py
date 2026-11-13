from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FH_")

    database_url: str
    environment: str = "local"

    # 세션 쿠키 (설계서 9장: HttpOnly·Secure, 만료·로그아웃)
    session_cookie_name: str = "fh_session"
    session_ttl_hours: int = 12
    session_remember_days: int = 30
    cookie_secure: bool = True

    # 상태 변경 요청을 허용할 브라우저 Origin (CSRF 방어)
    allowed_origins: list[str] = ["http://localhost:5173"]

    # 로그인 시도 제한
    login_max_attempts: int = 5
    login_window_seconds: int = 300

    # 비공개 파일 저장소 (웹 공개 경로 밖)
    storage_root: str = "/data/files"

    # "오늘", "이번 주", "이번 달" 계산 기준
    timezone: str = "Asia/Seoul"

    # 계약서 업로드 한도 (설계서 3장: 설정 가능한 한도)
    max_upload_mb: int = 20
    max_pdf_pages: int = 50

    # 작업자 (설계서 5장)
    worker_poll_seconds: float = 2.0
    job_lease_seconds: int = 120
    job_timeout_seconds: int = 600

    # OCR: "tesseract" 또는 "none"(OCR 없이 텍스트 PDF만 처리)
    ocr_engine: str = "tesseract"
    ocr_languages: str = "kor+eng"
    ocr_dpi: int = 300
    # 페이지당 추출 글자 수가 이보다 적으면 스캔 페이지로 보고 OCR한다
    min_text_chars_per_page: int = 20

    # AI 분석 (설계서 4장). 상용 모델: "gemini", "litellm", 또는 "fake"(테스트·화면 확인용, 외부 전송 없음)
    llm_commercial_provider: str = "gemini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    # 로컬 LLM 기본값 (선택)
    local_llm_model: str | None = None
    local_llm_api_base: str | None = None
    local_llm_api_key: str | None = None
    llm_timeout_seconds: int = 180
    # 한 번에 모델로 보내는 문서 글자 수 상한. 넘으면 페이지 단위로 나눠 보낸다
    analysis_chunk_chars: int = 60000


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
