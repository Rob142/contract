# Freelance Hub

AI 기반 프리랜서 업무 통합 관리 플랫폼 (팀 프로젝트 MVP)
계약서 업로드·조건 확인 → AI 계약 분석 → 프로젝트·칸반 → 인보이스·입금 관리

- 저장소: https://github.com/Rob142/contract
- 클론 주소: `https://github.com/Rob142/contract.git`

---

## 처음 시작하기 (아무것도 몰라도 돼요)

1. **Codex** 또는 **Claude Code**를 연다.
2. [`환경_세팅.md`](환경_세팅.md) 내용을 **전부 복사해서 붙여 넣는다.**
   - 복사하기 쉬운 원문 보기: https://raw.githubusercontent.com/Rob142/contract/main/환경_세팅.md
   - 이 문서는 저장소를 받기 전에 써요. 프로젝트 받기(클론)도 AI가 해요.
3. AI가 실행해도 되냐고 물으면 **허용**을 누르고, 시키는 대로 누른다.

Git과 Docker 설치, 프로젝트 받기, 내 컴퓨터에 맞는 포트 설정, 실행까지 AI가 다 해요.
(맥과 윈도우 모두 같은 방법이에요. 윈도우는 중간에 재부팅이 한 번 있을 수 있어요.)

---

## 매일 쓰는 말 (Codex에게)

| 하고 싶은 일 | Codex에게 이렇게 말하기 |
|---|---|
| 서버 켜기 | `서버 켜 줘` |
| 서버 끄기 | `서버 꺼 줘` |
| 팀원이 올린 최신 코드 받기 | `main 최신으로 받아서 내 브랜치에 합쳐 줘` |
| 내 작업 올리기 | `검사하고 커밋해서 내 브랜치로 푸시해 줘. PR 만드는 방법도 알려 줘` |
| 뭔가 안 될 때 | `서버가 안 열려. AGENTS.md 문제 해결 보고 고쳐 줘` |

## 팀 규칙

- `main`에는 직접 올리지 않아요. 각자 `feature/이름-작업` 브랜치에서 작업하고 **Pull Request**로 합쳐요.
- `.env` 파일과 API 키는 **절대 올리지 않아요.** (`.gitignore`로 막아 두었어요)
- AI 분석용 API 키는 팀 비공개 채널로 받아서, 웹의 **내 정보와 설정 → AI 설정**에 넣어요.

## 개발자용 자료

- 실행·검사 명령, 구조, 규칙: [`AGENTS.md`](AGENTS.md), [`docs/README.md`](docs/README.md), [`backend/README.md`](backend/README.md)
- 기획과 설계: [`docs/`](docs/)
