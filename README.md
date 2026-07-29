# toss-auto-trading

토스증권 OpenAPI로 국내주식의 단기 모멘텀을 탐색하고, 손실 한도와 주문 복구
장치를 적용해 자동매매하는 Python 프로젝트입니다.

수익을 보장하지 않습니다. 하루 3~5%는 매우 공격적인 목표이며, 이 프로그램은
목표 수익률보다 계좌 생존과 오류 시 안전 정지를 우선합니다.

## 현재 전략

- 거래대금 상위 국내주식에서 5분·15분 모멘텀과 거래량 급증을 확인합니다.
- 완성된 1분봉만 사용하며, 오래된 시세와 호가는 진입에 사용하지 않습니다.
- VWAP 과도 이격, 넓은 스프레드, 투자 유의 종목을 제외합니다.
- 코스피와 코스닥이 동시에 급락하면 신규 진입을 중단합니다.
- 수동 보유 종목과 실계좌 미체결 주문이 있으면 신규 진입을 피합니다.
- 진입은 최우선 매도호가 지정가로 제출해 최대 체결 가격을 제한합니다.
- 손절과 장 마감 청산은 체결을 우선해 시장가를 사용합니다.

기본 진입 시간은 `09:05~10:30`, `13:30~14:45`이며 15:10에 봇이
관리하는 포지션을 청산하고 15:20에 프로세스를 종료합니다.

## 안전 구조

- 주문 전에 로컬 상태 파일에 `clientOrderId`를 기록합니다.
- 주문 접수 직후 서버 `orderId`를 기록하고, 재시작 시 미결 주문을 조회·취소한
  뒤 체결 수량을 복구합니다.
- 부분 체결, 수수료와 세금을 실현 손익에 반영합니다.
- 계좌 자격·SOR 설정·계좌 제한 오류는 해당 거래일 신규 진입을 즉시 중단합니다.
- 종목 제한 오류는 해당 종목만 당일 제외합니다.
- 예기치 않은 오류가 연속 3회 발생하면 회로 차단기가 신규 진입을 중단합니다.
- 운영체제 파일 잠금으로 동일 모드의 두 번째 매매 프로세스를 차단합니다.
- `.env`, 로그, 상태 파일과 가상환경은 Git에 올리지 않습니다.

## 설치

Python 3.11 이상에서 다음 명령을 실행합니다.

```powershell
.\scripts\setup.cmd
```

프로젝트 루트의 `.env`에 토스 WTS에서 발급한 값을 직접 입력합니다.

```dotenv
TOSS_CLIENT_ID=
TOSS_CLIENT_SECRET=
TOSS_ACCOUNT_SEQ=
```

Client Secret은 채팅이나 GitHub에 올리지 마세요. 인증과 계좌 연결은 다음처럼
확인합니다.

```powershell
.\scripts\run.cmd check
```

## 실행

```powershell
.\scripts\run.cmd scan
.\scripts\run.cmd once
.\scripts\run.cmd run
.\scripts\run.cmd status
.\scripts\run.cmd report
.\scripts\stop.cmd
```

`scan`은 주문 없이 후보만 조회합니다. `once`와 `run`은 `.env`의
`TRADING_MODE`에 따라 주문할 수 있습니다.

실거래는 다음 확인 문자열까지 정확히 설정되어야 열립니다.

```dotenv
TRADING_MODE=live
LIVE_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY
```

평일 09:04 자동 시작 작업은 다음 명령으로 설치하거나 갱신합니다.

```powershell
.\scripts\install-task.cmd
```

Windows 실행 정책 때문에 `.ps1` 직접 실행이 막힐 수 있으므로 일반 사용 시
`.cmd` 파일을 사용하세요. 예약 작업은 `-ExecutionPolicy Bypass`로 등록됩니다.
수동 중지는 작업 스케줄러의 중지 버튼 대신 `stop.cmd`를 사용해야 자식 Python
프로세스까지 함께 종료됩니다.

## 운영 파일

- 상태: `state/live_portfolio.json` 또는 `state/paper_portfolio.json`
- 로그: `logs/trader.log`
- 일일 보고서: `report/YYYY-MM-DD.md`

상태와 로그는 로컬 전용입니다. 일일 보고서는 15:20 정상 종료 시 자동 갱신되며,
수동으로 `.\scripts\run.cmd report`를 실행해도 갱신됩니다.

## 실거래 전 확인

1. `run.cmd check`가 정상인지 확인합니다.
2. `run.cmd scan`이 주문 없이 정상 종료되는지 확인합니다.
3. 토스 WTS의 국내주식 주문 사전 동의와 투자자지시 거래소가 통합(SOR)인지
   확인합니다.
4. `run.cmd status`에서 `pending_order`가 없고 `entries_halted`가 false인지
   확인합니다.
5. 토스 앱에서 미체결 주문이 없는지 확인합니다.

`prerequisite-required`, `investor-exchange-not-integrated`,
`account-restricted` 오류가 발생하면 프로그램은 자동으로 신규 진입을 중단합니다.
원인을 WTS에서 해결한 뒤 다음 거래일 상태가 초기화될 때 재개됩니다.

## 테스트

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 공식 문서

- [토스증권 OpenAPI 가이드](https://developers.tossinvest.com/docs)
- [최신 OpenAPI 명세](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)
