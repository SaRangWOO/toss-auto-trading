# Project state

기준일: 2026-08-24 KST

## 운영 모드와 전략

- 로컬 기본 운영 모드는 `paper`이며 live는 정확한 이중 확인 설정이 필요하다.
- 고정 안전·유동성·시장 국면·stale data·position·일일 손실 guard가 적용된다.
- 시초 박스 돌파 후 고품질 지속 후보를 받는 보조 경로는 paper에서만 작동한다.
- paper 포지션은 5분·10분에 VWAP, 거래량, 체결 압력 proxy를 재평가한다.
- 강한 paper 추세는 고정 익절 대신 MFE 되돌림 한도로 관리한다.
- paper 체결은 슬리피지와 설정 가능한 수수료·매도세를 모사한다.

## Live 안전 상태

- live 시작 시 holdings, pending orders, buying power를 읽고 계좌 상태를
  로컬 state와 재동기화한다.
- `SUCCEEDED`만 신규 진입을 허용하며 `DEGRADED`, `FAILED`, `NOT_STARTED`,
  `IN_PROGRESS`는 신규 진입을 차단한다.
- 계좌 보유·수량·평균가와 미체결 주문은 계좌 결과를 우선한다.
- 주문 전 pending journal, server order ID 저장, 부분 체결, timeout 취소와
  재시작 복구가 구현돼 있다.
- 1주 live 검증 명령은 별도 확인 문자열과 `--no-retry`를 요구하며 자동매매
  runner와 분리돼 있다.

## 검증 범위

- 실제 Toss API나 실제 주문 없이 fake client 기반 단위 테스트로 검증한다.
- 비밀정보는 `.env`와 OS 자격증명 외에 기록하지 않는다.
- 실제 API schema, 계좌 권한, 수수료·세금, 부분 체결 지연, 15:35 live 강제
  청산은 별도 승인 환경에서 재검증이 필요하다.

## 알려진 제한

- paper 비용률은 보수적 모델값이며 실제 Toss 확정 요율이 아니다.
- paper는 호가 잔량 충격, 지연과 부분 체결을 완전히 재현하지 않는다.
- 주문 정정, 연속 거래손실 guard, 독립 총 노출 한도와 원격 경보가 없다.
- paper 실험을 live로 승격하기에는 관측 표본이 부족하다.
