# Repository Instructions

## 목적

Toss OpenAPI와 사전 정의된 단기 모멘텀 전략·리스크 기준으로 국내 주식의
매수와 매도를 자동 수행하는 시스템이다. 수익은 보장하지 않으며 계좌 보존과
오류 시 안전 정지를 우선한다.

## 주요 경로

- `src/toss_trader/`: API, 설정, 전략, broker, 엔진, 상태, 보고서, CLI
- `tests/`: 네트워크를 사용하지 않는 `unittest`
- `scripts/`: 환경 구성, 실행, 예약 작업, 비상 정지
- `docs/`: 상태, 구조, 설계 결정, 다음 작업
- `report/`: 추적 가능한 날짜별 운영 보고서
- `.env`, `.venv/`, `logs/`, `state/`: 로컬 전용이며 Git 추적 금지

## 환경 구성과 실행

```powershell
.\scripts\setup.cmd
.\scripts\run.cmd status
.\scripts\run.cmd check
.\scripts\run.cmd scan
.\scripts\run.cmd once
.\scripts\run.cmd run
.\scripts\run.cmd report
.\scripts\stop.cmd
```

- paper: `.env`의 `TRADING_MODE=paper`. 체결은 로컬에서 5bp 불리하게 즉시 모사한다.
- live: `TRADING_MODE=live`와 정확한 확인 문자열이 함께 설정되면 실제 주문이 가능하다.
- `check`, `scan`, `report`도 Toss API를 호출할 수 있다. `once`, `run`은 live에서 실제 주문이 가능하다.

## 테스트

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

## 자동매매 원칙

- live가 사전 승인되고 인증·계좌·주문 가능 상태와 안전 조건이 정상이면 전략 주문을 자동 수행한다.
- 진입과 청산은 매 주문마다 사용자 승인을 다시 요청하지 않는다.
- 전략·리스크 조건과 무관한 테스트 주문이나 임의 실거래는 금지한다.
- 계좌/WTS 설정, 미체결·pending 상태, 시세 신선도 또는 검증 상태가 불명확하면 실제 주문을 활성화하지 않는다.
- 실거래 안전성 검증에서는 실제 주문 대신 fake client 단위 테스트를 우선한다.

## 비밀정보

- 실제 Client ID·Secret, 계좌 식별값, 토큰, PAT, 개인키는 `.env` 또는 OS 자격증명 저장소에서만 관리한다.
- 비밀 값을 코드, 문서, 테스트, 로그, 명령 출력, 채팅, commit에 남기지 않는다.
- `.env`는 값이 아니라 존재 여부와 키 이름만 확인한다.
- 노출 또는 Git 이력 포함이 의심되면 commit/push를 중단하고 값 폐기와 조치를 보고한다.

## 변경과 Git

- 기존 구조와 정상 동작을 불필요하게 전면 재작성하거나 기능을 삭제하지 않는다.
- 변경 후 관련 테스트와 문서를 함께 갱신하고 문법·import·단위 테스트·비밀정보를 검증한다.
- 주요 코드·테스트·문서·소형 검증 산출물은 작업 범위에 게시가 포함된 경우 기능 브랜치에 commit/push한다.
- commit/push는 사용자의 명시적 요청 또는 현재 작업 지시에 포함된 경우에만 수행한다.
- `reset --hard`, `clean -fd`, rebase, force push, 강제 브랜치 삭제는 명시적 요청 없이 금지한다.
- 하나의 기능은 하나의 브랜치와 하나의 Codex 스레드에서 처리한다.
