# Next Task

## 작업명

프로그램 재시작 후 실제 계좌 상태 동기화

## 목표

live engine 시작 시 Toss 계좌의 매수 가능 금액, 실제 보유 종목과 미체결 주문을
조회하고 로컬 state와 비교한다. 불일치가 있으면 추측으로 거래하지 말고 실제
계좌 결과를 우선하여 안전하게 reconcile하거나 명확한 halt 상태로 전환한다.

## 권장 브랜치

`feat/live-account-state-sync`

## 읽을 파일

- `AGENTS.md`, `docs/PROJECT_STATE.md`, `docs/ARCHITECTURE.md`
- `src/toss_trader/api.py`
- `src/toss_trader/state.py`
- `src/toss_trader/broker.py`
- `src/toss_trader/engine.py`
- `tests/test_api.py`, `tests/test_state.py`, `tests/test_engine.py`

## 수정 허용 범위

- startup account snapshot과 reconcile에 필요한 최소 API parsing·state·engine code
- fake client 기반 holdings/open-order/restart unit test
- 관련 README와 상태·구조 문서

## 수정 금지 범위

- 전략 조건·수치, position sizing, 주문 유형의 임의 변경
- 실제 주문 호출, 임의 계좌 변경, 장시간 실행, backtest
- package 추가·업데이트, 대규모 refactor
- Git history 재작성, force push

## 필수 테스트

- 빈 계좌와 빈 state
- 실제 보유와 state 일치
- 실제 보유만 존재
- local position만 존재
- OPEN/PARTIAL 주문 존재
- pending에 server ID가 있는/없는 restart
- 수량·가격·side 불일치 시 halt
- reconcile 완료 전 신규 scan/order 차단
- paper 경로 회귀
- 전체 unit test, compileall, import smoke, secret scan

모든 테스트는 fake Toss client를 사용하고 실제 계좌·주문 API를 호출하지 않는다.

## 완료 기준

- live 시작 시 account snapshot이 성공해야만 신규 주문이 가능하다.
- 실제 계좌와 local state의 일치·불일치 처리 규칙이 test와 문서에 명시된다.
- 애매한 주문은 자동 재주문하지 않고 halt한다.
- 기존 26개 기준점 test와 신규 test가 모두 통과한다.
- credential, account 값, order ID 원문을 불필요하게 로그에 남기지 않는다.

## 예상 위험

- Toss holdings/order schema의 실제 응답이 unit fixture와 다를 수 있음
- 수동 보유와 bot 보유를 구분할 영속 metadata가 부족할 수 있음
- accepted order와 local journal 사이 crash window
- 부분 체결·수수료·세금의 중복 반영

## 다음 Codex 스레드 시작 명령문

> `C:\Users\wsr\Desktop\auto-trading`에서 `AGENTS.md`,
> `docs/PROJECT_STATE.md`, `docs/NEXT_TASK.md`를 먼저 읽고
> `feat/live-account-state-sync` 브랜치에서 “프로그램 재시작 후 실제 계좌
> 상태 동기화”만 구현해줘. 실제 Toss API나 주문은 호출하지 말고 fake client
> 단위 테스트로 빈 계좌, 보유 불일치, 미체결·부분 체결, pending crash window,
> reconcile 전 신규 주문 차단을 검증해줘. 전략 수치·주문 유형·패키지는 변경하지
> 말고, 완료 후 compileall·전체 unittest·import·비밀정보 검사를 실행한 뒤
> 문서를 갱신해줘.
