# Project state

기준일: 2026-10-07 KST

## 현재 운영 요약

- 현재는 병렬 paper v2로 baseline·continuation·retest 세 전략을 비교한다.
  실제 주문이나 자동 live 전환은 하지 않는다.
- 신규 진입은 오전 10:00~11:30, 정상 운용 완료 5거래일을 수집한 뒤 중단한다.
  진행 일수는 재시작해도 보존하며 고정 날짜 만료는 사용하지 않는다.
- 과거 live 관찰 기록은 아래 역사적 맥락이며 현재 모드를 의미하지 않는다.
- 시작 방법은 [실행 가이드](GETTING_STARTED.md), 상세 실험 정책은
  [병렬 paper v2](PARALLEL_PAPER_V2_2026-10-02.md), 폴더 구분은
  [폴더 안내](FOLDER_GUIDE.md)를 참조한다.

## 이전 운영 이력과 전략

- 2026-09-02부터 2주 micro-live 관찰을 시작했다. 초기 매수 상한은 45,000원,
  일일 신규 진입은 1회, 일일 손실 한도는 1,000원, 거래 위험은 0.5%다.
- 고정 안전·유동성·시장 국면·stale data·position·일일 손실 guard가 적용된다.
- 시초 박스 돌파 후 고품질 지속 후보를 받는 보조 경로는 paper에서만 작동한다.
- live에서도 같은 지속 후보를 진단·추적하지만 이 경로는 주문을 만들지 않는다.
- paper 포지션은 5분·10분에 VWAP, 거래량, 체결 압력 proxy를 재평가한다.
- 강한 paper 추세는 고정 익절 대신 MFE 되돌림 한도로 관리한다.
- paper 체결은 슬리피지와 설정 가능한 수수료·매도세를 모사한다.

## 외부 데이터 연구

- KIS의 공식 과거 분봉·외인기관 추정 API를 읽기 전용 연구 provider로 분리했다.
- 외부 CSV를 시간순으로 재생해 strict, Stock-in-Play, retest, flow-confirmed
  변형을 development/evaluation 구간으로 나눠 비교한다.
- 완료 봉만 신호에 사용하고 다음 1분봉 시가로 진입해 look-ahead를 차단한다.
- 모든 5/10/15/30분 성과와 MFE/MAE에 왕복 paper 비용을 반영한다.
- 외부 replay 결과는 paper 후보만 만들 수 있고 live 규칙을 자동 변경하지 않는다.

## Live 안전 상태

- live 시작 시 holdings, pending orders, buying power를 읽고 계좌 상태를
  로컬 state와 재동기화한다.
- `SUCCEEDED`만 신규 진입을 허용하며 `DEGRADED`, `FAILED`, `NOT_STARTED`,
  `IN_PROGRESS`는 신규 진입을 차단한다.
- 계좌 보유·수량·평균가와 미체결 주문은 계좌 결과를 우선한다.
- `LIVE_MANUAL_HOLDING_SYMBOLS`의 기존 수동 보유 종목은 봇 포지션 복구·청산
  대상에서 제외하며 신규 진입 후보에서도 제외한다.
- 주문 전 pending journal, server order ID 저장, 부분 체결, timeout 취소와
  재시작 복구가 구현돼 있다.
- 1주 live 검증 명령은 별도 확인 문자열과 `--no-retry`를 요구하며 자동매매
  runner와 분리돼 있다.

## 검증 범위

- 실제 Toss API나 실제 주문 없이 fake client 기반 단위 테스트로 검증한다.
- KIS provider 역시 fake transport로 인증·분봉 정규화·읽기 전용 endpoint를 검증한다.
- 비밀정보는 `.env`와 OS 자격증명 외에 기록하지 않는다.
- 실제 API schema, 계좌 권한, 수수료·세금, 부분 체결 지연, 15:35 live 강제
  청산은 별도 승인 환경에서 재검증이 필요하다.

## 알려진 제한

- paper 비용률은 보수적 모델값이며 실제 Toss 확정 요율이 아니다.
- paper는 호가 잔량 충격, 지연과 부분 체결을 완전히 재현하지 않는다.
- 주문 정정, 연속 거래손실 guard, 독립 총 노출 한도와 원격 경보가 없다.
- paper 실험을 live로 승격하기에는 관측 표본이 부족하다.
- historical orderbook·trade tick이 없으면 adaptive score 전체를 재현할 수 없다.
