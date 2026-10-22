# Toss Auto Trading

> Toss Securities OpenAPI 기반의 국내 주식 단기 모멘텀 자동매매 시스템
> A safety-first, evidence-driven momentum trading system for the Korean stock market.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Mode](https://img.shields.io/badge/default-paper%20trading-2E8B57)
![Tests](https://img.shields.io/badge/tests-offline%20unittest-4C1)
![License](https://img.shields.io/badge/license-not%20specified-lightgrey)

단순히 매수·매도 신호를 만드는 데 그치지 않고, **잘못된 주문을 내지 않는 구조**와
**실험 결과를 재현할 수 있는 관측 체계**에 초점을 둔 개인 프로젝트입니다. 후보 탐색,
다단계 필터링, paper/live broker 분리, 주문 복구, 일일 리스크 제한, 운영 보고서까지
핵심 자동매매 실행 흐름을 Python 표준 라이브러리로 구현했습니다.
선택적 Vibe 연구 환경은 별도 Python 패키지를, Paperclip은 Node/PostgreSQL을 사용합니다.

현재 기본 운영 모드는 `paper`입니다. 실거래 경로는 계좌 상태 동기화와 이중 잠금을
통과해야 하며, paper에서 검증 중인 전략은 live에 자동 반영되지 않습니다.

**처음 오셨나요?** [처음부터 따라 하는 실행 가이드](docs/GETTING_STARTED.md)에서
다운로드 → API 없이 테스트 → paper 연결 → 결과 확인 순서로 시작하세요.
[폴더 안내](docs/FOLDER_GUIDE.md)는 운영 본체와 별도 개발 공간을 설명합니다.

## 현재 운용 구성 (2026-10-22)

현재 운용은 **Paper Lab v3 전용 경로**입니다. 세 전략(시초 돌파 대조군·눌림목·
횡보 돌파)을 연구 자금/소액 예산으로 분리한 6개 가상 계좌로 비교합니다.
09:00 수집 시작과 실제 신규 진입 허용 시각은 다릅니다. 정책의 기본 진입 구간은
09:31~14:50, 강제 청산 시작은 15:15, 수집 종료는 15:40입니다.
실제 유효 설정은 실행 시 생성되는 manifest에 기록하며, 정책·코드가 달라지면
기존 실험 기록에 그대로 섞지 않습니다. [v3 상세 설명](docs/PAPER_LAB_V3.md)

[Paperclip 운영·연구 분담](research/paperclip/README.md)은 기존 매매와 독립적으로
운영 점검 → 성과 분석/탈락 분석 → 검증을 실행합니다. 로컬 Windows 프로세스 분담이며
별도 서버 분산이나 LLM 기반 자율 운용을 의미하지 않습니다.

| 무료 연구 기능 | 운용에 사용하는 근거 |
| --- | --- |
| 거래일지 대조 | 비용 차감 손익, 최고 수익 1/2건 제외, 비용 2배 시나리오 |
| 조건별 탈락 분석 | 단일 조건 탈락 에피소드의 30분 후 비용 차감 관측 성과 |
| 조건 순위 상관 | 최초 관측 시점의 거래량·상대 강도와 이후 수익률의 관계 |
| 거래 순서 1,000회 재배열 | 같은 거래 손익에서 발생할 수 있는 실현 자산 경로의 차이 |

정상 마감 확인 후 15:45부터 분석합니다. 조건 분석은 같은 정책 기간을 분리하고
표본이 부족하면 판단을 보류합니다. 관측 수익률은 대안 포트폴리오 수익이 아니며,
거래 순서 재배열은 미래 수익 확률을 예측하지 않습니다.
**연결된 연구 기능은 유료 모델/API·LLM 토큰을 사용하지 않습니다.** 로컬 자원은 사용하며,
분석 결과로 매매 설정을 자동 변경하거나 live로 전환하지 않습니다.

2026-10-21: [Vibe-Trading 연구 연결](research/vibe_trading/README.md)은 기존 paper
거래일지를 HKUDS Vibe-Trading의 분석기로 검증합니다. 별도 환경에서 계좌별
비용 차감 손익을 대조하며, 운영 엔진의 주문·설정을 자동 변경하지 않습니다.

### 이전 실험과 기본 설정의 차이 (v2 기록)

2026-10-08 추가: [Paper Lab v3](docs/PAPER_LAB_V3.md)는 봉 종료 시각을 명시적으로
처리하고, 두 독립 전략·시초 돌파 대조군을 연구 자금/실행 예산으로 나눠 비교하는
**별도 opt-in 경로**입니다. 아래 v2 설명을 자동 대체하지 않으며 live로 전환하지 않습니다.

공개 설정 예시는 단일 paper 모드입니다. 이전 **병렬 paper v2**는
`PAPER_PARALLEL_EXPERIMENT=true`를 별도로 설정해야 켜집니다. 기존 돌파·추세 지속·
돌파 후 재진입 세 전략을 독립 가상 계좌로 비교하며, 오전 `10:00~11:30`만 신규
진입합니다. 정상 운용 완료 5거래일 후 신규 진입을 멈추고, 재시작해도 진행 일수를
유지합니다. 휴장일이나 불완전한 운용일은 완료 일수에서 제외합니다.
상세 기준은 [v2 실험 설명](docs/PARALLEL_PAPER_V2_2026-10-02.md)을 참고하세요.
이는 수익성이 검증된 전략이나 자동 live 전환 기능이 아닙니다.

## 프로젝트 한눈에 보기

| 구분 | 내용 |
| --- | --- |
| 대상 | 국내 주식 단기 모멘텀·돌파 후보 |
| 데이터/주문 | Toss Securities OpenAPI REST polling, 선택적 KIS 읽기 전용 연구 데이터 |
| 핵심 흐름 | 종목 랭킹 → 안전·유동성 필터 → 시장 국면 → 돌파 → 적응형 점수 → 주문 |
| 리스크 관리 | 주문 금액·보유 수·일일 진입·일일 손실 제한, stale data 차단, 강제 청산 |
| 안정성 | single-instance lock, pending journal, 부분 체결·취소·재시작 복구, 계좌 reconciliation |
| 검증 | 네트워크 없는 `unittest`, paper 체결, filter funnel·shadow 사후 추적 |
| 운영 환경 | Windows, Python 3.11+, PowerShell, Windows Task Scheduler |

## 기본 엔진 전략 파이프라인 (v3와 별도)

```mermaid
flowchart LR
    A[고정 안전 필터] --> B[유동성<br/>거래대금 500억+]
    B --> C[시장 국면]
    C --> D[시초 박스<br/>돌파 후보]
    D --> E[시간대 적응형<br/>Volume Score]
    E --> F[VWAP · 호가 ·<br/>체결 Proxy Score]
    F --> G[최종 진입 점수]
    G --> H{운영 모드}
    H -->|paper| I[비용·슬리피지 모사]
    H -->|live + 이중 잠금| J[계좌 동기화 후 주문]
```

기본 진입 시간은 오전 `10:00~11:30`, 오후 `14:50~15:30`이며 `15:35`에
강제 청산합니다. 오전에는 09:00~09:30의 고가·저가로 만든 시초 박스를 기준으로
돌파와 거래량을 확인합니다. 기관 순매수 원천 데이터가 제공되지 않는 제약은 VWAP,
호가 불균형, 체결 강도성 지표를 조합한 proxy score로 보완합니다.

고정 안전장치를 통과한 뒤에도 다음 조건을 순차 적용합니다.

- 레버리지·인버스 상품 제외, 시세 신선도와 스프레드 검증
- 당일 거래대금 500억 원 이상과 가격 변동 범위 확인
- 시장 지수의 5분·15분 흐름으로 하락 국면 필터링
- 시초 박스 돌파, 적응형 거래량, VWAP, 호가, 체결 proxy 점수화
- 현금·포지션·일일 진입 횟수·일일 손익 한도와 최종 신호 재검증

## 설계에서 중요하게 다룬 문제

### 1. paper와 live의 격리

`PaperBroker`와 `LiveBroker`를 분리했습니다. paper는 불리한 슬리피지와 수수료·세금
모델을 반영하지만 외부 주문을 만들지 않습니다. 실험 중인 추세 지속 보조 진입과
5분·10분 포지션 재평가는 paper에서만 실행됩니다.

### 2. 계좌 상태를 진실의 원천으로 사용

live 시작 시 보유 종목, 미체결 주문, 주문 가능 금액을 조회해 로컬 상태와 대조합니다.
동기화가 `SUCCEEDED`가 아니면 신규 진입을 차단하되, 기존 포지션의 위험 청산 경로는
유지합니다.

### 3. 주문 장애와 재시작 복구

주문 제출 전에 pending journal을 기록하고, 서버 주문 ID·부분 체결·timeout 취소를
추적합니다. 프로세스가 재시작되면 미완료 주문을 복구 대상으로 읽어 중복 주문 위험을
줄입니다.

### 4. 결과보다 근거를 남기는 실험

각 후보가 어느 필터에서 탈락했는지 `filter_funnel`에 기록하고, 진입하지 않은 후보도
5/10/15/30분 수익률과 MFE/MAE를 `shadow_tracking`으로 추적합니다. 전략 변경은
단일 사례가 아니라 서로 다른 episode의 사후성과를 비교한 뒤 paper에 한정해 적용합니다.

### 5. 외부 데이터로 가설을 먼저 압축

과거 1분봉을 시간순으로 replay해 현재 strict 조건, Stock-in-Play, 돌파 retest,
외인·기관 수급 확인 변형을 같은 비용 모델로 비교합니다. development/evaluation을
날짜순으로 분리하고 다음 봉 시가로만 진입해 look-ahead를 막습니다. 결과가 좋아도
live에는 자동 반영하지 않고 paper 실험 후보로만 표시합니다.

## 시스템 구조

```mermaid
flowchart TD
    API[Toss OpenAPI] --> CLIENT[TossClient<br/>OAuth · retry · throttling]
    CLIENT --> ENGINE[TradingEngine]
    ENGINE --> STRATEGY[Strategy<br/>filters · scores · exits]
    ENGINE --> RISK[Risk guards<br/>cash · exposure · daily limits]
    ENGINE --> BROKER{Broker}
    BROKER --> PAPER[PaperBroker]
    BROKER --> LIVE[LiveBroker]
    ENGINE --> STATE[(Local state)]
    ENGINE --> OBS[Logs · reports<br/>funnel · shadow tracking]
    LIVE --> RECON[Account reconciliation]
    RECON --> ENGINE
    EXT[KIS read-only / licensed CSV] --> RESEARCH[Historical replay]
    RESEARCH --> EVAL[Development · Evaluation report]
    EVAL -->|candidate only| PAPER
```

## 디렉터리 구조

**현재 운영 본체는 이 폴더(`auto-trading/`)입니다.** 실행은 루트의 `scripts/`만
사용합니다. 처음 보는 분은 [폴더 안내](docs/FOLDER_GUIDE.md)를 먼저 확인하세요.
별도 개발 브랜치 두 개는 `development-worktrees/` 안에 보존하며, 자동 실행하지 않습니다.

```text
auto-trading/
├─ src/toss_trader/
│  ├─ api.py              # OAuth, 시세·계좌·주문 REST client
│  ├─ broker.py           # paper 체결과 live 주문 수명주기
│  ├─ config.py           # 환경 설정, 검증, live 이중 잠금
│  ├─ engine.py           # 스캔, 리스크, 주문, 포지션, 복구 orchestration
│  ├─ reconciliation.py   # live 계좌와 로컬 상태 동기화
│  ├─ kis_data.py         # 선택적 KIS 분봉·수급 읽기 전용 provider
│  ├─ research.py         # 외부 분봉 replay와 전략 변형 비교
│  ├─ reporting.py        # 날짜별 운영 보고서
│  ├─ state.py            # 포트폴리오·주문 상태 저장
│  ├─ strategy.py         # 진입 점수, 수량, 청산·포지션 재평가
│  └─ cli.py              # CLI와 single-instance runner
├─ tests/                 # 네트워크를 사용하지 않는 unittest
├─ config/paper_lab_v3.json # v3 기본 실험 정책
├─ research/
│  ├─ vibe_trading/       # 고정 upstream 분석 함수 연결·설치·연구 안내
│  └─ paperclip/          # 로컬 운영/성과/연구/검증 담당
├─ scripts/               # 설치, 실행, 예약 작업, watchdog, 비상 정지
├─ docs/                  # 아키텍처, 설계 결정, 실험·운영 검토
├─ report/                # Git에 보존하는 소형 날짜별 운영 보고서
├─ reports/               # 로컬 상세 진단 데이터 (Git 제외)
├─ logs/                  # 로컬 runner·trading 로그 (Git 제외)
├─ state/                 # 로컬 계좌·주문 상태 (Git 제외)
├─ research_data/         # 외부 원천·정규화 데이터 (Git 제외)
├─ research_output/       # replay 결과 (Git 제외)
├─ development-worktrees/ # 별도 브랜치 개발 공간 (로컬 전용, 운영 본체 아님)
│  ├─ live-account-sync/  # 실계좌 상태 동기화 개발 브랜치
│  └─ market-regime-adaptive/ # 시장 국면 적응형 전략 개발 브랜치
├─ .env.example           # 비밀값 없는 설정 예시
└─ pyproject.toml
```

로컬 `.env`, `.venv/`, `logs/`, `state/`, `reports/`, `research_data/`,
`research_output/`, `development-worktrees/`는 루트 저장소의 Git 추적에서 제외됩니다.
개발 공간 내부의 코드는 각각 기존 Git 브랜치로 계속 관리됩니다.

## 빠른 시작

### 요구 환경

- Windows PowerShell
- Python 3.11 이상
- Git (저장소 복제용)
- Toss Securities OpenAPI 사용 권한

기본 매매 런타임에는 외부 패키지가 없습니다. 선택적 연구 환경은 별도 설치합니다.

```powershell
git clone https://github.com/SaRangWOO/toss-auto-trading.git auto-trading
cd auto-trading
.\scripts\setup.cmd
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

`.env`에 발급받은 값을 로컬에서만 입력합니다.

```dotenv
TOSS_CLIENT_ID=
TOSS_CLIENT_SECRET=
TOSS_ACCOUNT_SEQ=
TRADING_MODE=paper
LIVE_TRADING_CONFIRM=
```

실행 명령은 다음과 같습니다.

```powershell
.\scripts\run.cmd status  # 로컬 상태 확인
.\scripts\run.cmd check   # API·설정 점검
.\scripts\run.cmd scan    # 후보 스캔
.\scripts\run.cmd once    # 1회 전략 사이클
.\scripts\run.cmd run     # 장중 반복 runner
.\scripts\run.cmd report  # 일일 보고서 생성
.\scripts\stop.cmd        # 예약 작업·runner 비상 정지
```

`check`, `scan`, `report`도 Toss API를 호출할 수 있습니다. `once`, `run`은 live
설정에서 실제 주문을 만들 수 있으므로 연결 테스트 용도로 실행하면 안 됩니다.

## 외부 데이터 replay

### Paper v3와 무료 연구 실행

기본 설치와 API 설정 후 아래 명령을 사용합니다. v3는 paper 전용이며,
기존 실험 manifest가 불일치하면 초기화하거나 덮어쓰지 말고 원인을 확인합니다.

```powershell
.\scripts\run.cmd paper-lab-run
# 장 마감 후 별도 터미널에서 보고서 생성
.\scripts\run.cmd paper-lab-report
# 선택 사항: 검증 환경 Python 3.13, Git 및 패키지 다운로드 연결 필요
.\research\vibe_trading\setup.ps1
# YYYY-MM-DD를 실제 수집 완료일로, 출력 폴더를 새 경로로 변경
.\research_data\vibe-trading\venv\Scripts\python.exe research/vibe_trading/free_research.py --through YYYY-MM-DD --output research_output/vibe-trading/new-review
```

결과는 지정 폴더의 `REPORT.md`, `analysis.json`, `episodes.json`입니다.
Paperclip이 구성된 운영 VM에서는 이 분석이 자동 실행되고,
`research_output/paperclip/YYYY-MM-DD/research-v2.json`과 `validation-v2.json`에서
보고서 경로를 확인할 수 있습니다. Paperclip 서버 설치본·DB·로컬 런타임 설정은
저장소에 포함하지 않습니다. 새 PC에서 `install-task.ps1`만 실행하면 서버가
설치되는 것은 아닙니다. [구성 전제와 운영 안내](research/paperclip/README.md)

### KIS 읽기 전용 연구

한국투자 OpenAPI의 최대 1년 과거 분봉과 외인·기관 추정 집계를 주문 기능 없이
읽기 전용으로 수집할 수 있습니다. 기본은 비활성이며 로컬 `.env`에 별도 KIS
인증정보와 `KIS_DATA_ENABLED=true`가 있어야 명시적 research 명령이 동작합니다.

```powershell
# 과거 분봉 수집
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m toss_trader.cli research-fetch-kis `
  --project-root . --symbols 005930,000660 `
  --start-date 2026-01-02 --end-date 2026-08-24

# 외인·기관 추정 snapshot 수집
.\.venv\Scripts\python.exe -m toss_trader.cli research-fetch-flow `
  --project-root . --symbols 005930,000660

# 전략 변형 replay
.\.venv\Scripts\python.exe -m toss_trader.cli research-backtest `
  --project-root . --candles research_data/kis/minute_bars.csv `
  --flows research_data/kis/flow_snapshots.csv `
  --split-date 2026-06-01
```

상세 스키마, 데이터 권한, 비용과 승격 경계는
[외부 데이터 연구 가이드](docs/EXTERNAL_RESEARCH.md)를 참조하세요.

## 안전한 live 활성화

다음 두 설정이 동시에 정확해야 live 주문 경로가 열립니다.

```dotenv
TRADING_MODE=live
LIVE_TRADING_CONFIRM=I_UNDERSTAND_REAL_MONEY
```

설정만으로 충분하지 않습니다. WTS 허용 IP, 국내주식 사전 동의, 주문 가능 상태와
live startup reconciliation도 모두 정상이어야 신규 진입이 허용됩니다. 전략과 무관한
테스트 주문은 코드와 운영 원칙상 허용하지 않습니다.

## 테스트

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m compileall -q src tests research
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

단위 테스트는 fake client를 사용하며 실제 Toss API와 실제 주문을 호출하지 않습니다.

## 검토 자료

- [포트폴리오 소개와 설계 과정](docs/PORTFOLIO_OVERVIEW.md)
- [현재 아키텍처](docs/ARCHITECTURE.md)
- [구현 및 안전 상태](docs/PROJECT_STATE.md)
- [전략·운영 설계 결정](docs/DECISIONS.md)
- [기관 수급 proxy 설계](docs/INSTITUTIONAL_PROXY.md)
- [외부 데이터 수집·replay 가이드](docs/EXTERNAL_RESEARCH.md)
- [주간 진입 전략 검토](docs/WEEKLY_ENTRY_REVIEW_2026-08-22.md)
- [paper 포지션 관리 실험](docs/PAPER_POSITION_MANAGEMENT_2026-08-24.md)
- [날짜별 운영 리포트](report/README.md)

대표 주간 검토에서는 6개의 서로 다른 shadow episode와 2건의 paper 왕복 거래를
분석해, 엄격한 돌파 필터를 전면 완화하지 않고 고품질 추세 지속 경로만 paper에
추가했습니다. 이 결과는 전략 검증 방식의 예시이며 수익성을 입증하는 표본은 아닙니다.

## 현재 한계와 다음 과제

- paper 체결은 호가 잔량 충격, 네트워크 지연, 부분 체결을 완전히 재현하지 않습니다.
- 실제 API schema, 수수료·세금, 장 마감 강제청산은 승인된 live 환경에서 재검증이 필요합니다.
- 주문 정정, 연속 거래손실 guard, 독립적인 전체 노출 한도, 원격 알림은 미구현입니다.
- paper 실험을 live로 승격하기에는 서로 다른 시장 국면의 관측 표본이 더 필요합니다.
- historical 호가·체결 틱이 없으면 외부 replay로 adaptive score 전체를 재현할 수 없습니다.

## 보안과 면책

인증정보·계좌 식별값은 `.env` 또는 OS 자격증명 저장소에서만 관리하며 저장소와
운영 보고서에 기록하지 않습니다. 이 프로젝트는 학습·포트폴리오·개인 검증 목적이며,
투자 권유가 아닙니다. 수익을 보장하지 않고 실제 거래에는 원금 손실 위험이 있습니다.

공식 API 문서: [Toss Securities OpenAPI 가이드](https://developers.tossinvest.com/docs)
