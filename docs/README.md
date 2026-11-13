# Freelance Hub

AI 기반 프리랜서 업무 통합 관리 플랫폼 MVP. 기획은 `docs/프리랜서_플랫폼_MVP_기획_구현_설계서.pdf`, 할 일은 `docs/전체_구현_TODO.md`를 본다.

## 로컬 실행

처음 세팅은 루트 [`README.md`](../README.md)의 프롬프트로 Codex에게 맡기거나, [`AGENTS.md`](../AGENTS.md) 1장을 따른다.
포트·접속 범위·윈도우 폴링(`FILE_POLLING`)은 컴퓨터마다 `.env`에서만 바꾼다.

```bash
cp .env.example .env      # 처음 한 번, 비밀번호를 바꾸고 포트를 확인한다
docker compose up -d --build
```

| 서비스 | 주소 | 설명 |
| --- | --- | --- |
| web | http://localhost:5173 (`WEB_PORT`) | React + TypeScript (Vite). `/api` 요청은 api로 프록시 |
| api | http://127.0.0.1:8010/api/docs (`API_PORT`) | FastAPI (Swagger 문서) |
| db | 127.0.0.1:5442 (`POSTGRES_PORT`) | PostgreSQL 17. 스키마는 migrate 서비스가 Alembic으로 적용 |

브라우저는 반드시 `http://localhost:<WEB_PORT>`로 연다. 상태 변경 요청은 같은 출처(Origin = Host)에서만 받는다.

## 검사

```bash
docker compose exec api pytest && docker compose exec api ruff check . && docker compose exec api mypy app
docker compose exec web npm run typecheck && docker compose exec web npm run lint && docker compose exec web npm test
```

## API 타입 갱신

백엔드 API를 바꾸면 프론트 타입을 다시 생성한다.

```bash
docker compose exec web npm run gen:api   # → frontend/src/api/schema.d.ts
```

자세한 내용은 `backend/README.md`를 본다.
