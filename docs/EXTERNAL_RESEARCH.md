# External data research and replay

기준일: 2026-08-25 KST

## 목적

하루씩 쌓이는 내부 paper 표본만 기다리지 않고, 과거 1분봉과 외부 수급 자료로
전략 가설을 먼저 대량 검증한다. 외부 검증은 live 진입 규칙을 자동 변경하지 않으며,
조건을 통과한 변형도 paper 실험 후보로만 올린다.

```text
공식/허가된 외부 데이터
  -> 공통 CSV 정규화
  -> 시간순 replay (완료 봉만 사용)
  -> 다음 1분봉 시가 진입
  -> 비용 반영 5/10/15/30분 성과 + MFE/MAE
  -> development/evaluation 분리 비교
  -> paper 후보 결정
  -> 별도 관찰 후 live 승격 심사
```

## 데이터 소스

### 한국투자 OpenAPI

선택적인 읽기 전용 데이터 provider로 사용한다. 주문 endpoint는 구현하지 않는다.

- 주식일별분봉조회 `[국내주식-213]`
  - endpoint: `/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice`
  - 한 호출 최대 120건
  - 공식 안내상 서버 보관 범위 내 최대 1년 분봉
- 종목별 외인기관 추정가집계 `[국내주식-046]`
  - endpoint: `/uapi/domestic-stock/v1/quotations/investor-trend-estimate`
  - 외국인·기관 자료는 정해진 장중 시각에 입력되는 추정 누계이며 실시간 틱이 아니다.

공식 예제:

- [주식일별분봉조회](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/inquire_time_dailychartprice)
- [종목별 외인기관 추정가집계](https://github.com/koreainvestment/open-trading-api/tree/main/examples_llm/domestic_stock/investor_trend_estimate)

### KRX 또는 허가된 데이터 vendor

KRX 정보데이터시스템의 종목 시세·투자자별 거래실적은 장기 시장 국면과 수급
검증에 사용할 수 있다. 한국투자의 1년 범위를 넘는 2~3년 분봉은 KRX 데이터 상품
또는 이용 권한이 명확한 vendor에서 확보해 공통 CSV로 변환한다. 웹 화면의 비공식
endpoint를 우회 호출하거나 이용 조건을 위반하는 수집은 사용하지 않는다.

- [KRX 정보데이터시스템](https://data.krx.co.kr/contents/MDC/MAIN/main.jspx)

## 설정

KIS 설정은 로컬 `.env`에만 둔다. Toss 주문 인증과 별개이며 Git에 올리지 않는다.

```dotenv
KIS_DATA_ENABLED=true
KIS_APP_KEY=
KIS_APP_SECRET=
KIS_BASE_URL=https://openapi.koreainvestment.com:9443
KIS_REQUEST_INTERVAL_SECONDS=0.20
```

`KIS_DATA_ENABLED=false`가 기본이다. research 명령을 명시적으로 실행하지 않으면
KIS API를 호출하지 않으며, trading runner는 이 설정을 읽어 진입 판단에 사용하지
않는다.

## 데이터 수집

### 과거 1분봉

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m toss_trader.cli research-fetch-kis `
  --project-root . `
  --symbols 005930,000660 `
  --start-date 2026-01-02 `
  --end-date 2026-08-24
```

기본 출력은 `research_data/kis/minute_bars.csv`다. 동일 timestamp/symbol은
원자적으로 병합되어 재실행해도 중복되지 않는다. 요청량은 종목 수×거래일×일별
페이지 수로 증가하므로 작은 종목·날짜 범위부터 확인한다.

### 외인·기관 추정 snapshot

```powershell
.\.venv\Scripts\python.exe -m toss_trader.cli research-fetch-flow `
  --project-root . `
  --symbols 005930,000660
```

기본 출력은 `research_data/kis/flow_snapshots.csv`다. 이 값은 증권사 장중 추정
누계이므로 “기관 3분 연속 순매수”와 같은 틱 단위 사실로 해석하지 않는다.

## 공통 입력 스키마

### minute bars CSV

필수 열:

```text
timestamp,symbol,open,high,low,close,volume
```

선택 열:

```text
trading_amount,source
```

`trading_amount`는 해당 시점의 누적 거래대금이다. 없으면 replay가 `close×volume`을
누적해 근사한다. timestamp에 timezone이 없으면 KST로 해석한다.

### flow CSV

```text
timestamp,symbol,institution_net_buy,foreign_net_buy,program_net_buy,source
```

### event CSV

```text
timestamp,symbol,news_flag
2026-08-24T09:45:00+09:00,005930,true
```

replay는 신호 시각 이전 timestamp의 사건만 사용한다. 공시·뉴스 timestamp는 실제
최초 공개 시각이어야 하며, 기사 수정 시각이나 장 마감 후 분류 결과를 사용하면 안 된다.

## replay 실행

```powershell
.\.venv\Scripts\python.exe -m toss_trader.cli research-backtest `
  --project-root . `
  --candles research_data/kis/minute_bars.csv `
  --flows research_data/kis/flow_snapshots.csv `
  --events research_data/events.csv `
  --split-date 2026-06-01 `
  --output-dir research_output/current
```

출력:

- `research-summary.md`: 변형·구간별 비교표와 해석 경계
- `research-summary.json`: 모든 signal/trade와 상세 수치

신호는 현재 봉이 완전히 끝난 뒤 평가하고 반드시 다음 1분봉 시가로 진입한다.
각 수익률에는 paper 설정의 매수·매도 수수료, 매도세와 양방향 슬리피지를 차감한다.

## 비교하는 전략 변형

| 변형 | 설명 |
| --- | --- |
| `strict_ohlcv` | 현재 가격·거래대금·모멘텀·거래량·VWAP·시초 박스 조건의 OHLCV 근사 |
| `strict_stock_in_play` | strict에 2% gap, 2x opening RVOL 또는 사전 공개 event를 추가 |
| `retest_stock_in_play` | 최근 돌파 후 opening high retest/reclaim과 2개 완료 봉 유지를 요구 |
| `retest_flow_confirmed` | retest에 기관 양수 및 외인/프로그램 중 하나의 양수 snapshot을 추가 |

한 symbol/day/variant에서는 최초 신호만 사용해 반복 30초 관측으로 표본이 부풀지
않게 한다. 수급은 같은 거래일의 신호 시각 이전 2시간 이내 snapshot만 사용해
전일 수급이나 오래된 추정치가 확인 조건으로 재사용되지 않게 한다.

## 평가와 승격 기준

- 날짜순 70/30 자동 분할 또는 `--split-date`로 development/evaluation을 분리한다.
- 비용 후 15·30분 평균수익, 30분 승률, profit factor, MFE, MAE, 최대 누적
  drawdown을 비교한다.
- evaluation에서 완료된 30분 표본 30건 이상, 비용 후 평균수익 양수,
  profit factor 1.2 초과일 때만 `paper_candidate=yes`가 가능하다.
- 이 표시는 paper 실험 후보일 뿐이다. historical OHLCV에는 호가, 체결 틱,
  실제 지연과 계좌 체결이 없으므로 live 승격은 항상 차단된다.
- 최종 paper 승격 전에는 시장 지수 국면, 종목 상장폐지·거래정지, 수정주가,
  survivorship bias와 event timestamp 품질을 별도로 검증한다.

## 현재 한계

- KIS 분봉 보관은 최대 1년이며 호출량 제한을 고려해야 한다.
- 수급 snapshot은 입력 시각이 제한된 추정치라 실시간 기관 주문 흐름이 아니다.
- historical orderbook/trade tick이 없으면 현재 adaptive score 전체를 동일하게
  재현할 수 없다.
- 현재 replay는 오전 opening-range 가설 비교에 집중한다. 장 막판 거래량 폭발
  전략은 별도의 auction·프로그램매매 데이터셋으로 검증해야 한다.
