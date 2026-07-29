# Project State

기준일: 2026-07-29 KST

기준 브랜치: `chore/project-baseline`

기준점의 부모: `d6b22fd` (`agent/safer-live-execution`)

이번 기준점 감사에서는 실제 Toss API, 계좌 조회, 시세 조회, 주문 API를
호출하지 않았다. “검증 완료”는 네트워크 없는 단위 테스트 또는 정적 검사로
재현된 항목만 뜻한다.

## 현재 구현

- 표준 라이브러리 기반 OAuth client credentials, 토큰 cache·만료·401 재발급
- API group별 client throttle, 429/5xx/network retry, gzip/deflate 처리
- 계좌, 보유 종목, 매수 가능 금액, 매도 가능 수량, 수수료 조회
- 거래대금 순위, 현재가, 1분봉, 호가, 종목 경고, 장 일정, 시장 지수 조회
- 주문 생성, 주문 상세·목록, 미체결 목록, 취소, client order ID
- 모멘텀 스캔, 수량 계산, paper/live broker, 포지션·손익·일일 guard
- pending journal, 부분 체결, 취소 후 복구, 오류별 계좌 halt/종목 block
- JSON 상태, UTF-8 로그, 날짜별 보고서, 단일 인스턴스, 예약 작업, 비상 정지

## Toss OpenAPI 감사

| 항목 | 상태 | 근거/한계 |
|---|---|---|
| OAuth 토큰 발급 | 구현됐으나 실제 검증 필요 | `issue_token()`; 이번 감사에서 미호출 |
| 토큰 만료·재발급 | 구현됐으나 실제 검증 필요 | 만료 60초 여유, 401 1회 강제 갱신 |
| 계좌 식별 header | 구현됐으나 실제 검증 필요 | `X-Tossinvest-Account` |
| 잔고·보유·매수 가능 금액 | 구현됐으나 실제 검증 필요 | account/holdings/buying-power |
| 현재가·1분봉·순위·호가 | 구현됐으나 실제 검증 필요 | REST polling |
| 매수·매도 주문 생성 | 구현됐으나 실제 검증 필요 | 요청 직렬화만 단위 검증 |
| 주문·체결·미체결 조회 | 구현됐으나 실제 검증 필요 | order detail/list OPEN |
| 주문 취소 | 구현됐으나 실제 검증 필요 | timeout/recovery에서 사용 |
| 주문 정정 | 미구현 | timeout 주문은 취소만 수행 |
| 부분 체결·미체결 parsing | 구현 및 검증 완료 | fake response 단위 테스트 |
| 오류 code 분류 | 부분 구현 | 알려진 계좌/종목 code만 분기 |
| 호출 제한·재시도 | 구현됐으나 실제 검증 필요 | unit coverage 없음 |
| 중복 요청 방지 | 부분 구현 | client ID·pending·open-order·lock; 신호 fingerprint 없음 |

## 전략 감사

`.env.example` 기준 기본값은 09:05~10:30/13:30~14:45 진입, 종목당
10만 원, 최대 2종목, 하루 3회 진입, 일손실 1%, 수익 잠금 2%, stop 0.8%,
take profit 1.5%, trailing 0.6%, 15:10 청산이다. 로컬 `.env`의 실제
유효 값은 비밀정보 보호를 위해 읽지 않았으므로 확인 필요다.

- 구현: 거래대금 순위, 당일 1분봉 5/15분 모멘텀, 거래량 급증,
  최근 최대 20개 봉 종가×거래량 가중 평균, spread, 시장 지수 filter
- 구현: 장 초반·중후반 창, 손절·익절·trailing, 일손실·수익 잠금, 장 종료 전 청산
- 부분 구현: 투자경고/주의는 rankings option과 warnings 응답 존재 여부로 제외
- 확인 필요: 단기과열·VI가 Toss warnings 응답으로 모두 포괄되는지
- 물타기: 구현하지 않음. 내부 보유 종목은 신규 scan에서 제외

README의 “VWAP”은 session VWAP가 아니라 최근 최대 20개 1분봉의
종가×거래량 가중 평균이므로 이번 기준점에서 표현을 바로잡았다.

## 리스크 감사

| 항목 | 상태 |
|---|---|
| 1회 최대 금액·종목 비중·보유 수 제한 | 구현 및 단위 검증 |
| 전체 최대 투자 금액 | 부분 구현: 종목 비중×종목 수 외 독립 한도 없음 |
| 일일 최대 손실·수익 잠금 | 구현 및 단위 검증 |
| 연속 거래손실 제한 | 미구현 |
| 연속 시스템 오류 차단 | 구현됐으나 run loop 실동작 검증 필요 |
| 매수 가능 금액 | 구현; paper 수량 단위 검증, live 실제 검증 필요 |
| 보유 수량 초과 매도 | 구현됐으나 실제 검증 필요 |
| 부분·미체결 처리 | 단위 검증 완료, 실제 검증 필요 |
| stale 시세·진입 가격 이동 검사 | 구현됐으나 일부만 단위 검증 |
| 재시작 후 pending 주문 복구 | 단위 검증 일부 완료 |
| 실제 계좌 전체 상태 우선 동기화 | 부분 구현 |
| 장 종료 청산 | paper 단위 검증, live 실제 검증 필요 |
| 비상 정지 | script 정적 검증; 실제 실행 검증 안 함 |
| paper/live 로그 분리 | 부분 구현: 같은 파일에 mode field 기록 |

## 테스트와 실제 검증

2026-07-29 기준:

- `compileall`: 성공
- `unittest`: 26/26 성공
- 검증 범위: 설정 이중 잠금, paper/live 초기화, 주문 body, 체결 parsing,
  부분/미체결, account open-order gate, pending round-trip·복구, 수량,
  모멘텀/시장 filter, 손절·익절·trailing, 일손실, paper 장마감, lock,
  비상 정지 script 구조
- import smoke: 전체 `toss_trader` module import 성공
- 실제 검증 아님: OAuth, 계좌/시세, 실제 주문·취소·체결, 수수료·세금,
  예약 종료, 실제 비상 정지

과거 `report/2026-07-29.md`에 API 읽기와 실행 기록이 있으나 이번 기준점에서
재현하지 않았으므로 현재 연결 성공의 근거로 사용하지 않는다.

## paper와 live 상태

- paper: 로컬 5bp 불리한 즉시 체결. 외부 API 시세는 사용하며 수수료·세금,
  호가 충격, 지연은 충분히 모사하지 않는다.
- live: 주문 code는 영구 차단되어 있지 않다. 정확한 mode/확인 문자열,
  credential/account 설정이 있으면 전략 주문을 자동 제출한다.
- 감사 시점에 `live_trader.lock`, 관련 Python process와 평일 예약 작업
  `Running` 상태를 확인했다. 실행 중이라는 사실만 확인했으며 주문·체결
  정상 여부와 현재 로컬 전략 수치는 확인하지 않았다.

## 알려진 문제와 위험

- 시작 시 buying power를 읽지만 실제 holdings/open orders로 내부 포지션을
  완전히 재구성하지 않는다. 내부와 실제 계좌 불일치 시 계좌 우선 원칙 미완성.
- server order ID 저장 전에 process가 종료된 pending은 자동 해결하지 못하고 halt한다.
- 정정 주문, 연속 거래손실 제한, 독립적인 총 투자한도, alert/원격 kill switch가 없다.
- 종목 warnings 의미, API schema 변경, 계좌 유형·SOR·사전동의는 확인 필요다.
- `stop.ps1`은 process를 강제 종료하므로 진행 중 서버 주문 확인이 필요하다.
- paper/live가 같은 `logs/trader.log`를 사용한다.

## 주요 파일

- `config.py`: 환경 로딩·기본값·live 잠금
- `api.py`: Toss REST client
- `strategy.py`: 신호·수량·청산 조건
- `broker.py`: paper/live 주문 실행
- `engine.py`: scan·risk·주문·포지션·복구
- `state.py`: 상태·pending JSON
- `cli.py`: 명령·단일 인스턴스
- `reporting.py`: 날짜별 운영 보고서

## Toss 연결 미완료 설정

- 로컬 credential/account ID 유효성: 확인 필요
- WTS 허용 IP, 국내주식 사전 동의·위험 고지, 투자자 유형, SOR: 확인 필요
- 계좌의 현재 보유·미체결·주문 가능 상태: 확인 필요
- local `.env`의 선택 설정과 문서 기본값 일치 여부: 확인 필요

## 다음 권장 작업

`docs/NEXT_TASK.md`의 “프로그램 재시작 후 실제 계좌 상태 동기화” 한 건만
별도 브랜치와 새 Codex 스레드에서 수행한다.
