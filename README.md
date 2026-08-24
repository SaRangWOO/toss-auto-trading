# toss-auto-trading

Toss OpenAPI로 국내 주식의 단기 모멘텀 후보를 찾고, 사전에 정한 자금·손실
한도 안에서 paper 또는 live 주문을 자동 실행하는 Python 프로젝트입니다.
live가 사전 승인된 뒤에는 전략 진입과 손절·익절·시간 청산을 주문별 추가
승인 없이 수행합니다. 수익을 보장하지 않으며 실거래 손실이 발생할 수 있습니다.

## 현재 운영 방식

- 거래대금 상위 종목을 REST polling으로 조회합니다.
- 당일 1분봉의 5분·15분 모멘텀, 거래량 급증, 최근 20개 봉의
  종가×거래량 가중 평균, 스프레드와 시장 지수 상태를 검사합니다.
- 기본 진입 시간은 `09:05~10:30`, `13:30~14:45`입니다.
- 손절, 익절, 트레일링 스톱과 15:10 강제 청산을 적용합니다.
- 보유 종목은 신규 후보에서 제외하므로 손실 포지션 물타기를 하지 않습니다.
- 주문 전 pending journal을 저장하고 접수 ID, 부분 체결, 취소와 재시작 복구를 처리합니다.

실제 수치는 `.env.example`의 기본값이며 로컬 `.env`가 이를 덮어쓸 수 있습니다.

## 프로젝트 구조

```text
src/toss_trader/
  api.py          Toss 인증·시세·계좌·주문 REST client
  config.py       .env 로딩, 기본값, live 이중 잠금
  strategy.py     진입 신호, 수량, 청산 조건
  broker.py       paper 체결과 live 주문 추적
  engine.py       스캔, 리스크, 주문, 포지션, 복구
  state.py        로컬 JSON 상태
  reporting.py    날짜별 운영 보고서
  cli.py          명령 진입점과 단일 인스턴스 잠금
tests/            네트워크 없는 단위 테스트
scripts/          설정·실행·예약 작업·비상 정지
docs/             실제 구현 상태와 설계 문서
report/           Git에 보존하는 소형 날짜별 보고서
```

로컬 `.env`, `.venv/`, `logs/`, `state/`는 Git에서 제외됩니다.

## 요구 환경과 설치

- Windows PowerShell
- Python 3.11 이상
- 외부 런타임 패키지 없음

```powershell
.\scripts\setup.cmd
```

스크립트는 `.venv`를 만들고 Python 버전을 확인합니다. 실행 스크립트가
`src`를 `PYTHONPATH`에 지정하므로 별도 package 설치는 필요하지 않습니다.

## 환경 설정

```powershell
Copy-Item .env.example .env
```

`.env`에 다음 값을 직접 입력합니다. 실제 값은 채팅이나 Git에 올리지 않습니다.

```dotenv
TOSS_CLIENT_ID=
TOSS_CLIENT_SECRET=
TOSS_ACCOUNT_SEQ=
TRADING_MODE=paper
LIVE_TRADING_CONFIRM=
```

live 전에는 Toss WTS의 허용 IP, 국내주식 사전 동의·위험 고지, 투자자 유형,
거래소 통합(SOR)과 계좌 주문 가능 상태도 별도로 확인해야 합니다.

## paper 모드

```dotenv
TRADING_MODE=paper
LIVE_TRADING_CONFIRM=
```

```powershell
.\scripts\run.cmd check
.\scripts\run.cmd scan
.\scripts\run.cmd once
.\scripts\run.cmd run
```

paper 주문은 기본 5bp의 불리한 슬리피지와 설정 가능한 매수·매도 수수료,
매도세 가정을 적용해 즉시 체결로 모사합니다. 기본 비용률은 실제 Toss 계좌의
확정 요율이 아니라 전략을 보수적으로 평가하기 위한 모델값입니다. 부분 체결,
호가 잔량에 따른 충격과 주문 지연은 아직 완전히 재현하지 않습니다.
paper 체결은 상태 파일에도 주문 형태로 저장되어 날짜별 보고서의 왕복 거래와
체결 기준 손익 계산에 사용됩니다.

paper 모드에는 2026-08-22 주간 검토에서 추가한 보수적인 오전 추세 지속
보조 진입 실험이 포함됩니다. 최근 10분 안의 시초 박스 돌파, 박스 위 2개 봉
유지, 높은 적응형 점수와 거래량·호가·체결 proxy, 제한된 VWAP/돌파 이격이
2회 연속 확인되어야 하며 당일 첫 진입에만 적용됩니다. 기존 안전·유동성·시장
국면·스프레드·리스크·최종 신호 필터는 그대로 적용되고 live에서는 이 경로를
평가하지 않습니다. 설정값은 `.env.example`의 `PAPER_CONTINUATION_*` 항목에서
확인할 수 있습니다.

paper 보유 포지션은 진입 후 5분과 10분에 VWAP, 최근 거래량 유지율과 체결
압력 proxy를 다시 평가합니다. 약한 신호가 겹치거나 10분까지 추세 진전이
없으면 조기 청산하고, 강한 추세가 확인되면 고정 익절 대신 최대 수익 대비
되돌림 한도로 관리합니다. 이 경로와 비용 모델은 이번 paper 관찰을 위한
실험이며 live 진입·청산 로직에는 적용되지 않습니다. 자세한 기준과 승격
조건은 `docs/PAPER_POSITION_MANAGEMENT_2026-08-24.md`에 기록합니다.

## live 모드

다음 두 설정이 동시에 정확해야 live 주문 경로가 열립니다.

```dotenv
TRADING_MODE=live
LIVE_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY
```

```powershell
.\scripts\run.cmd once
.\scripts\run.cmd run
```

`once`와 `run`은 전략·리스크 조건을 충족하면 실제 주문을 자동 제출할 수
있습니다. 단순 연결 확인이나 테스트 목적으로 실행하지 마세요. 전략과 무관한
임의 주문은 금지합니다. 평일 09:04 예약 작업은 다음으로 등록합니다.

```powershell
.\scripts\install-task.cmd
```

## 상태, 주문과 체결 확인

```powershell
.\scripts\run.cmd status
.\scripts\run.cmd report
```

- 상태: `state/paper_portfolio.json` 또는 `state/live_portfolio.json`
- 로그: `logs/trader.log` (`mode=paper|live`가 각 거래 이벤트에 포함됨)
- 날짜별 보고서: `report/YYYY/MM/YYYY-MM-DD.md`
- shadow 후보 사후성과: `reports/shadow_tracking/YYYY-MM-DD.json`
- paper 5분·10분 보유 점검: `reports/position_reviews/YYYY-MM-DD.jsonl`
- 실제 접수·미체결·체결·취소의 최종 근거: Toss WTS의 해당 계좌 주문 내역

`status`는 로컬 상태만 읽습니다. live의 `report`는 계좌와 주문 API를
조회할 수 있습니다. 내부 상태와 Toss 계좌가 다르면 현재 코드는 자동으로
전체 상태를 교정하지 못하므로 실행을 중지하고 확인해야 합니다.

## 비상 정지

```powershell
.\scripts\stop.cmd
```

예약 작업을 중지하고 이 프로젝트의 `toss_trader.cli run` Python 프로세스를
강제 종료합니다. 강제 종료 시 진행 중 주문은 서버에 남을 수 있으므로 Toss
WTS에서 미체결 주문과 보유 종목을 즉시 확인해야 합니다.

## 테스트

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

단위 테스트는 실제 Toss API와 실제 주문을 호출하지 않습니다.

## 구현 상태와 제한

OAuth, 계좌·시세 조회, 후보 스캔, paper 체결, live 주문 제출·조회·취소,
부분 체결 반영, pending journal, 일일 손실/수익 잠금, 단일 인스턴스와 비상
정지가 구현되어 있습니다. 자세한 검증 상태는 `docs/PROJECT_STATE.md`를
참조하세요.

주요 제한은 다음과 같습니다.

- 재시작 시 실제 보유 종목·미체결 주문과 내부 포지션의 완전한 동기화가 없습니다.
- 미체결 주문은 취소하지만 주문 정정은 구현하지 않았습니다.
- 연속 시스템 오류 제한은 있으나 연속 거래손실 제한은 없습니다.
- 종목별 비중과 보유 종목 수 제한은 있으나 별도의 전체 포트폴리오 한도는 없습니다.
- paper/live가 같은 로그 파일을 사용하고 paper 체결 모사는 단순합니다.
- live 체결·수수료·세금·장 마감 복구는 실제 계좌 환경에서 재검증이 필요합니다.

## 공식 문서

- [Toss Securities OpenAPI 가이드](https://developers.tossinvest.com/docs)
- [OpenAPI 명세](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)
