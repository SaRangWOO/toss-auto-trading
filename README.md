# toss-auto-trading

토스증권 OpenAPI를 사용하는 국내 주식 단기 모멘텀 자동매매 프로젝트입니다.

기본값은 **실제 주문을 전혀 보내지 않는 paper 모드**입니다. 목표 수익률은
보장하지 않으며, 하루 3~5%는 손실 위험도 매우 큰 공격적인 목표입니다.

## 전략

- 국내 시장 거래대금 상위 종목을 실시간 스캔
- 일중 상승률 2~12% 범위만 검토
- 5분·15분 모멘텀, 1분봉 거래량 급증, VWAP 상단 유지 확인
- 호가 스프레드 0.4% 이하 종목만 진입
- 투자경고·투자위험·단기과열·VI 등 유의 종목 제외
- 장 초반 `09:05~10:30`, 중후반 `13:30~14:45`에만 신규 진입
- 종목당 최대 10만원, 계좌의 10%, 위험 예산 중 가장 작은 값으로 수량 결정
- 일일 신규 진입 횟수 제한
- 기본 손절 -0.8%, 익절 +1.5%, 트레일링 스톱 0.6%
- 하루 -1% 도달 시 전량 정리 후 신규 진입 중지
- 하루 +2% 도달 시 수익 보호를 위해 전량 정리 후 신규 진입 중지
- 15:10 전량 정리하여 오버나이트 금지
- 15:20 프로세스 자동 종료
- 손실 포지션 물타기 금지

## 사전 준비

1. Python 3.11 이상을 설치합니다.

   ```powershell
   winget install --id Python.Python.3.13 -e --source winget
   ```

2. 토스증권 WTS의 `설정 > Open API`에서 현재 VM의 공인 IP를 허용 IP로
   등록합니다.
3. 프로젝트의 `.env`에 Client Secret을 입력합니다. Secret은 채팅이나
   GitHub에 올리지 마세요.

   ```dotenv
   TOSS_CLIENT_SECRET=여기에_로컬에서만_입력
   ```

4. 로컬 환경을 준비합니다.

   ```powershell
   .\scripts\setup.cmd
   ```

5. 인증과 계좌를 확인합니다.

   ```powershell
   .\scripts\run.cmd check
   ```

   출력된 `accountSeq`를 `.env`의 `TOSS_ACCOUNT_SEQ`에 입력합니다.

## 모의 실행

```powershell
.\scripts\run.cmd scan
.\scripts\run.cmd once
.\scripts\run.cmd run
```

거래 상태는 `state/paper_portfolio.json`, 로그는 `logs/trader.log`에
저장됩니다. 두 경로는 Git에서 제외됩니다.

평일 09:04 자동 시작 작업을 설치하려면 다음을 실행합니다. 예약 실행은
15:20에 스스로 종료되며, Windows 사용자 세션이 로그인된 상태여야 합니다.

```powershell
.\scripts\install-task.cmd
```

## 실거래 잠금

충분한 기간 동안 paper 모드 결과와 체결 가정을 검증하기 전에는 실거래를
켜지 마세요. 실거래에는 아래 두 설정이 동시에 필요합니다.

```dotenv
TRADING_MODE=live
LIVE_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY
```

실거래 엔진은 봇이 자체 상태 파일에 기록한 포지션만 관리합니다. 수동 보유
종목에는 관여하지 않습니다. 시장가 주문은 급등주에서 슬리피지가 커질 수
있으므로 최초 실거래는 `MAX_TRADE_KRW`를 더 낮춰 검증하세요.

## 테스트

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 공식 문서

- [토스증권 OpenAPI 가이드](https://developers.tossinvest.com/docs)
- [서버 제공 OpenAPI 명세](https://openapi.tossinvest.com/openapi-docs/latest/openapi.json)
- [Rate Limits 및 시작하기](https://openapi.tossinvest.com/openapi-docs/overview.md)
