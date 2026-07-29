# Design Decisions

| 결정 | 반영 상태 | 근거/비고 |
|---|---|---|
| 기본 모드는 paper | 반영 | `Settings.from_project()` |
| credential/account 값은 `.env`에서만 관리 | 반영 | `config.py`, `.gitignore` |
| live는 mode와 정확한 확인 문자열을 모두 요구 | 반영 | `Settings.validate()` |
| 사전 승인된 live 주문은 건별 재승인을 요구하지 않음 | 반영 | `once`, `run` |
| 전략과 무관한 임의 주문 금지 | 운영 규칙 | `AGENTS.md` |
| 손실 포지션 물타기 제외 | 반영 | 보유 symbol scan 제외 |
| 종목 금액·비중·개수·일일 진입 제한 | 반영 | 수량 계산과 engine guard |
| 일일 최대 손실·수익 잠금 시 신규 진입 중단 | 반영 | `_daily_guard()` |
| stop·take profit·trailing과 장 종료 전 청산 | 반영 | `exit_reason()`, force exit |
| 매수는 시장성 limit, 위험 청산은 market | 반영 | `LiveBroker` |
| 주문 전 pending과 client ID를 저장 | 반영 | `_new_pending()` |
| 계좌 오류는 전체 halt, 종목 오류는 symbol block | 부분 반영 | 알려진 error code만 분류 |
| account open order와 중복 process 차단 | 반영 | `list_orders("OPEN")`, lock |
| 실제 계좌 상태가 내부 상태보다 우선 | 부분 반영 | full startup sync 미구현 |
| 미체결은 자동 정정 또는 취소 판단 | 부분 반영 | timeout 취소만 구현 |
| 연속 손실 제한 | 미반영 | system exception counter만 존재 |
| paper/live 로그 분리 | 부분 반영 | 동일 파일, event에 mode 기록 |
| Git 게시 전 test·secret 검증 | 운영 규칙 | `AGENTS.md` |
