# AGENTS.md — Freelance Hub 작업 안내 (Codex·AI 에이전트용)

이 파일은 이 저장소에서 일하는 AI 에이전트(Codex 등)가 따르는 안내서다.
팀원 대부분은 개발 비전공자이고 **맥과 윈도우가 섞여 있다**. 처음 세팅은 루트의 `환경_세팅.md`를 따른다 (Git·Docker 설치부터). 이 파일은 세팅 이후의 일상 작업·규칙·문제 해결 안내다.

## 0. 꼭 지킬 원칙

1. **명령은 에이전트가 직접 실행한다.** 사용자에게 터미널 명령을 입력하라고 하지 않는다.
2. 사용자가 직접 해야 하는 일은 **클릭 단위로 한 단계씩** 쉬운 말로 안내하고, 끝났다는 답을 기다린다. 예: 관리자 암호 입력, 설치 창의 "동의", 재부팅, Docker Desktop 첫 실행 약관
3. **호스트에 Python·Node·npm·PostgreSQL을 설치하지 않는다.** DB·백엔드·프론트는 모두 Docker 컨테이너 안에서 돈다. `npm install`도 컨테이너가 알아서 한다.
4. 컴퓨터마다 다른 값(포트, 접속 범위, 비밀번호, 윈도우 폴링)은 **`.env`에서만** 바꾼다. `docker-compose.yml`, `vite.config.ts`, 백엔드 설정 파일의 포트·주소는 고치지 않는다.
5. `.env`와 비밀값(비밀번호, API 키)은 **커밋하지 않고, 화면에 그대로 출력하지 않는다.**
6. `main` 브랜치에 바로 커밋하지 않는다. 작업은 `feature/이름-작업` 브랜치에서 한다.
7. 되돌릴 수 없는 명령은 **반드시 먼저 묻는다.** 예: `docker compose down -v`(DB 삭제), `git reset --hard`, `git push --force`, 다른 프로그램 종료
8. 진행 상황은 짧게 알린다. 예: "Docker 설치 확인 중", "처음 실행이라 5~10분 걸려요"

## 1. 처음 환경 세팅

### 1-1. 운영체제 확인

- 맥: `uname -s` 결과가 `Darwin`. 칩은 `uname -m`으로 본다 (`arm64` = Apple 실리콘, `x86_64` = 인텔)
- 윈도우: PowerShell에서 `$env:OS` 결과가 `Windows_NT`. 윈도우에서는 **PowerShell 명령**을 쓴다

### 1-2. Git

`git --version`으로 확인하고, 없으면 설치한다.

| | 설치 |
|---|---|
| 맥 | `xcode-select --install` → 뜨는 창에서 "설치"를 누르라고 안내 (Homebrew가 있으면 `brew install git`) |
| 윈도우 | `winget install --id Git.Git -e --source winget` → 끝나면 Codex(또는 터미널)를 다시 열어야 인식된다고 안내 |

이름·이메일이 없으면(`git config --global user.name`이 비어 있으면) 사용자에게 물어서 설정한다.

### 1-3. Docker Desktop

`docker --version`과 `docker compose version`으로 확인한다.

**설치가 안 되어 있으면**

| | 설치 |
|---|---|
| 맥 | Homebrew가 있으면(`brew --version`) `brew install --cask docker`. 없으면 https://www.docker.com/products/docker-desktop/ 에서 칩에 맞는 버전(Apple 실리콘 / 인텔)을 받아 `Docker.dmg`를 열고 Docker 아이콘을 Applications로 끌어 놓으라고 안내 |
| 윈도우 | ① `wsl --status`로 WSL2를 확인한다. 없으면 `wsl --install`(관리자 권한 필요). **재부팅이 필요하다고 안내**하고, 재부팅 뒤 다시 이 단계부터 진행한다. ② `winget install -e --id Docker.DockerDesktop` |

**실행과 준비 확인**

- 맥: `open -a Docker`. 윈도우: `Start-Process "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"`
- 처음 실행하면 약관 동의와 로그인 화면이 뜬다. "Accept"를 누르고 로그인은 건너뛰어도 된다(Skip)고 안내한다.
- `docker info`가 성공할 때까지 5초 간격으로 최대 3분 기다린다. 실패가 계속되면 5장을 본다.

### 1-4. 저장소와 작업 브랜치

- 이 폴더가 이미 저장소면(`git rev-parse --is-inside-work-tree`) 건너뛴다. 아니면 `git clone https://github.com/Rob142/contract.git`로 받고 `contract` 폴더로 이동한다.
- 비공개 저장소라 인증에 실패하면
  - 윈도우: Git 설치에 포함된 로그인 창(브라우저)이 뜨니 GitHub로 로그인하라고 안내한다.
  - 맥: `gh`가 없으면 `brew install gh`로 설치한 뒤 `gh auth login --web`을 실행한다. 화면의 코드를 브라우저에 입력하라고 안내한다. Homebrew가 없으면 GitHub Desktop 설치를 권한다.
- 최신 `main`을 받는다: `git switch main && git pull`
- 작업 브랜치를 만든다: `git switch -c feature/<이름>-<작업>`. 이름은 영어 소문자로, 사용자에게 묻는다. 예: `feature/jiyoon-invoice-ui`

### 1-5. `.env` 만들기 (이 컴퓨터에 맞추기)

`.env`가 이미 있으면 **덮어쓰지 않는다.** 아래 항목 중 빠진 것만 채운다.

1. `.env.example`을 복사해 `.env`를 만든다.
2. **DB 비밀번호**를 무작위 32자로 바꾼다. `POSTGRES_PASSWORD`와 `DATABASE_URL` 안의 비밀번호를 같은 값으로 바꾼다. 값은 출력하지 않는다.
   - 맥: `openssl rand -hex 16`
   - 윈도우: `-join ((48..57)+(97..102) | Get-Random -Count 32 | ForEach-Object {[char]$_})`
3. **포트 확인:** `POSTGRES_PORT`(기본 5442), `API_PORT`(8010), `WEB_PORT`(5173)마다 다른 프로그램이 쓰는지 본다. 쓰고 있으면 1씩 올려 빈 번호를 찾아 `.env`에 적는다. `DATABASE_URL`의 포트도 맞춘다.
   - 맥: `lsof -nP -iTCP:<포트> -sTCP:LISTEN` (출력이 없으면 비어 있음)
   - 윈도우: `Get-NetTCPConnection -LocalPort <포트> -State Listen -ErrorAction SilentlyContinue` (출력이 없으면 비어 있음)
4. **윈도우면 `FILE_POLLING=true`**, 맥이면 `false`로 둔다. 윈도우는 이 값이 없으면 코드를 고쳐도 화면에 바로 반영되지 않는다.
5. **접속 범위**는 기본 `WEB_BIND=127.0.0.1`(내 컴퓨터만)이다. 사용자가 "휴대폰이나 같은 와이파이의 다른 기기에서도 보고 싶다"고 할 때만 `0.0.0.0`으로 바꾸고, 내 IP를 찾아 알려 준다.
   - 맥: `ipconfig getifaddr en0`
   - 윈도우: `Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch 'Loopback|vEthernet|WSL' } | Select-Object -ExpandProperty IPAddress`
   - 이때 윈도우 방화벽 허용 창이 뜨면 "허용"을 누르라고 안내한다.

### 1-6. 실행

```
docker compose up -d --build
```

- 처음에는 이미지 내려받기와 빌드 때문에 **5~10분** 걸린다고 미리 알린다.
- `docker compose ps`로 확인한다. `db`·`api`·`worker`·`web`은 `running`이고, `migrate`는 종료 코드 0으로 끝나야 정상이다.
- API 확인: `http://127.0.0.1:<API_PORT>/api/v1/health`가 응답해야 한다. 윈도우는 `curl.exe`로 확인한다. 실패하면 `docker compose logs api --tail 50`을 본다.
- 웹 확인: `http://localhost:<WEB_PORT>`가 열려야 한다. 처음에는 `web`이 패키지를 설치하느라 1~2분 더 걸릴 수 있으니 `docker compose logs web --tail 20`에 `Local:`이 나올 때까지 기다린다.

### 1-7. 검사 (선택이지만 권장)

```
docker compose exec -T api pytest -q
docker compose exec -T web npm run -s typecheck
```

### 1-8. 마무리 보고

사용자에게 아래 내용을 쉬운 말로 알려 준다.

- 접속 주소: `http://localhost:<WEB_PORT>`. **반드시 이 주소로 연다** (`127.0.0.1`과 섞어 쓰면 로그인이 풀릴 수 있다)
- 처음에는 회원가입부터 한다. 계정은 각자 컴퓨터에만 있고 팀원끼리 공유되지 않는다.
- AI 분석을 쓰려면 웹의 **내 정보와 설정 → AI 설정**에서 API 키를 넣는다. 키는 팀 비공개 채널로 받고, 코드나 채팅에 붙여 넣지 않는다.
- 지금 작업 브랜치 이름
- 끄기·켜기: "Docker Desktop만 켜져 있으면 다음부터는 Codex에게 '서버 켜 줘'라고 하면 돼요"

## 2. 매일 쓰는 요청과 할 일

| 사용자 요청 | 에이전트가 할 일 |
|---|---|
| "서버 켜 줘" | Docker Desktop 실행 확인 → `docker compose up -d` → 주소 안내 |
| "서버 꺼 줘" | `docker compose stop` (데이터는 남는다) |
| "최신으로 받아 줘" | 변경 사항이 있으면 먼저 커밋할지 묻는다 → `git switch main && git pull` → 작업 브랜치로 돌아가 `git merge main` → `docker compose up -d --build`(백엔드 패키지가 바뀌었을 수 있다) |
| "저장해 줘 / 올려 줘" | 검사(1-7) → 바뀐 파일 요약 → 커밋 메시지 제안 → 커밋 → `git push -u origin <브랜치>` → GitHub에서 Pull Request를 만드는 방법 안내 (`gh`가 있으면 `gh pr create`) |
| "화면이 이상해 / 안 열려" | 5장 문제 해결 |

## 3. 프로젝트 구조

| 경로 | 내용 |
|---|---|
| `backend/` | FastAPI(Python 3.13), SQLAlchemy, Alembic 마이그레이션(`alembic/versions`, 원시 SQL은 `alembic/sql`), 작업자(`app/worker`), 테스트(`tests/`) |
| `frontend/` | React 19 + TypeScript + Vite. API 타입은 `src/api/schema.d.ts`(자동 생성) |
| `docs/` | 기획 설계서, 구현 TODO, UX 개선안, 수정 계약 반영 설계 등 |
| `docker-compose.yml` | db(PostgreSQL 17) · migrate · api · worker · web |

컨테이너 안 명령은 `docker compose exec -T <서비스> <명령>`으로 실행한다.

## 4. 개발 규칙

- **DB 스키마**는 Alembic 마이그레이션으로만 바꾼다 (`backend/alembic/versions/000N_*.py`, 번호는 이어서). 적용: `docker compose run --rm migrate`
- **API를 바꾸면** 프론트 타입을 다시 만든다: `docker compose exec -T web npm run gen:api`
- **백엔드 패키지**(`requirements*.txt`)를 바꾸면 이미지 세 개를 함께 다시 빌드한다: `docker compose build api worker migrate && docker compose up -d`
- 금액은 원 단위 `Decimal`로만 계산한다. API에서는 문자열로 주고받는다.
- 발행한 인보이스는 고치지 않는다 (취소 후 재발행). DB 트리거가 막는다.
- 다른 사용자의 데이터는 존재 여부도 드러내지 않는다 (404).
- 커밋 전 검사

```
docker compose exec -T api pytest -q
docker compose exec -T api ruff check .
docker compose exec -T api mypy app
docker compose exec -T web npm run -s typecheck
docker compose exec -T web npm run -s lint
docker compose exec -T web npm test
```

## 5. 문제 해결

| 증상 | 원인과 조치 |
|---|---|
| `Cannot connect to the Docker daemon` / `docker: command not found` | Docker Desktop이 꺼져 있거나 설치 직후 인식 전이다. 1-3의 실행 명령을 쓰고, 설치 직후라면 Codex를 다시 열라고 안내 |
| `port is already allocated` / `address already in use` | 1-5의 3번처럼 빈 포트를 찾아 `.env`만 바꾸고 `docker compose up -d` |
| 윈도우: `WSL 2 installation is incomplete` | `wsl --update` 실행(관리자) 후 Docker Desktop 재시작 |
| 윈도우: 코드를 고쳐도 반영되지 않음 | `.env`에 `FILE_POLLING=true` → `docker compose up -d` |
| `migrate` 실패 | `docker compose logs migrate`. DB가 늦게 뜬 경우가 많으니 `docker compose up -d`를 한 번 더 |
| `web`에서 `EACCES` / `permission denied` (node_modules) | `docker compose run --rm --user root web chown -R node:node /app/node_modules` 후 `docker compose up -d web` |
| 로그인했는데 바로 풀림 / "허용되지 않은 위치" 오류 | `localhost`와 `127.0.0.1`을 섞어 썼다. `http://localhost:<WEB_PORT>` 하나로만 연다 |
| 화면은 뜨는데 데이터가 안 나옴 | `docker compose ps`로 `api`가 running인지 본다. 아니면 `docker compose logs api --tail 80` |
| DB를 완전히 초기화하고 싶다 | `docker compose down -v`는 **모든 계정·계약서·인보이스를 지운다.** 반드시 사용자에게 확인을 받은 뒤 실행 |
| Apple 실리콘에서 빌드가 아주 느림 | 정상이다 (처음 한 번). Docker Desktop 설정에서 "Use Rosetta"는 켜지 않아도 된다 |
