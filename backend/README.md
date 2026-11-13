# Freelance Hub 백엔드

FastAPI + SQLAlchemy 2 + PostgreSQL 17. 모든 실행은 Docker Compose로 한다(호스트에 Python 패키지 설치 불필요).

## 실행

```bash
# 저장소 루트에서
cp .env.example .env          # 처음 한 번, 비밀번호를 바꾼다
docker compose up -d --build  # db → migrate(alembic upgrade head) → api
```

- API: http://127.0.0.1:8010/api/v1 (포트는 `.env`의 `API_PORT`)
- API 문서(Swagger): http://127.0.0.1:8010/api/docs
- DB: `127.0.0.1:5442`, 접속 정보는 `.env`

코드를 고치면 api와 worker가 자동 재시작된다. **`requirements.txt`나 `Dockerfile`을 바꾸면 백엔드 이미지 3개를 모두 다시 빌드한다.** api만 빌드하면 worker가 이전 패키지로 돌아 실패한다.

```bash
docker compose build api worker migrate && docker compose up -d
```

## AI 분석 (Gemini)

`.env`에 `GEMINI_API_KEY`를 넣고 `docker compose up -d api worker`. 모델은 `GEMINI_MODEL`(기본 `gemini-2.5-flash`)로 바꾼다.
키 없이 화면만 확인하려면 `LLM_COMMERCIAL_PROVIDER=fake`(외부 전송 없는 가짜 모델). 테스트는 항상 가짜 모델을 쓴다.

## 검사

```bash
docker compose exec api pytest          # <db>_test DB를 만들어 마이그레이션 후 실행, 끝나면 삭제
docker compose exec api ruff check .
docker compose exec api ruff format .
docker compose exec api mypy app
```

## 스키마 변경

스키마의 원본은 `alembic/sql/`과 `alembic/versions/`다. ORM 모델(`app/db/models.py`)은 매핑만 한다.

```bash
docker compose exec api alembic revision -m "add something"   # 새 마이그레이션 파일 생성 후 직접 작성
docker compose run --rm migrate                               # 적용
```

## 구조

| 경로 | 역할 |
| --- | --- |
| `app/main.py` | 앱 생성, 미들웨어(요청 ID → Origin 검사), 오류 처리기 |
| `app/api/routes/` | 라우트 (`/health`, `/auth`, `/users/me`) |
| `app/api/deps.py` | 현재 사용자, 소유권 검사 `get_owned_or_404` |
| `app/core/errors.py` | 공통 오류 형식 `{"error": {code, message, details}}`, DB 오류 → 409 매핑 |
| `app/core/idempotency.py` | `Idempotency-Key` 처리 `run_idempotent` (발행·입금·확정용) |
| `app/core/versioning.py` | 낙관적 잠금 `assert_version` |
| `app/core/pagination.py` | 커서 페이지 처리 |
| `app/core/storage.py` | 파일 저장소 인터페이스, 로컬 구현 |
| `app/core/audit.py` | 감사 기록 |
| `app/core/csrf.py` | 상태 변경 요청의 Origin 허용 목록 검사 |
| `app/core/rate_limit.py` | 로그인 시도 제한 (프로세스 메모리, 단일 프로세스 전제) |

## 인증 방식

- 로그인하면 HttpOnly·SameSite=Lax 세션 쿠키(`fh_session`)를 발급한다. DB에는 토큰의 SHA-256만 저장한다.
- 세션 만료는 기본 12시간, "로그인 상태 유지"를 고르면 30일이다. 로그아웃하면 서버에서 즉시 무효가 된다.
- 프론트는 같은 출처로 `/api`를 호출한다(Vite 개발 서버 프록시). 그래서 CORS 설정은 필요 없다. 허용 Origin은 `FH_ALLOWED_ORIGINS`로 정한다.
- 운영 환경에서는 `FH_COOKIE_SECURE=true`(HTTPS)로 둔다.
