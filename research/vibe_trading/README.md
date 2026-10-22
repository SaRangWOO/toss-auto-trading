# Toss paper v3 × HKUDS Vibe-Trading

Toss의 시초 돌파·눌림목·횡보 돌파 전략은 기존 체결/위험 엔진에 두고,
Vibe-Trading의 실제 거래일지 분석기를 별도 Python 환경에서 실행한다.
운영 종속성이나 `src/toss_trader`를 변경하지 않는다.

참조: https://github.com/HKUDS/Vibe-Trading

## 현재 연결된 기능

- paper ledger → 계좌별 generic CSV 매수/매도 체결 일지 변환.
- 원화 수수료·세금·양방향 슬리피지를 보존하고 FIFO 손익을 원장과 대조.
- 거래당 순손익, 실현손익 곡선의 최대 누적 손실, 승률, 청산 사유, 초 단위
  보유시간, 최고 수익 1/2건 제외, 비용 2배 시나리오를 계산.
- 원장의 시장 맥락 비교 결과와 전략 설명/정책을 연구 패킷에 포함.
- upstream의 `analyze_trade_journal`로 profile/behavior 분석 실행.
  behavior의 일 단위 휴리스틱은 한국 장중 전략의 유효성 판정에 직접 사용하지 않는다.

이 구성은 upstream 전체 웹 UI/MCP/LLM 서비스 설치가 아니다. AI 모델 키,
브로커 연결, 주문 도구 없이 실제 upstream 분석 함수를 호출하는 연결이다.
Vibe-Trading의 자연어 전략 생성·모델 분석을 활성화하려면 모델 선택과 인증이
추가로 필요하다. 현재 리포트는 코드 계산 결과이며 AI가 작성한 분석으로 표시하지 않는다.

## 폴더

```text
auto-trading/
  research/vibe_trading/          연결 코드·실행 스크립트·upstream revision
  research_data/vibe-trading/     upstream 원본·전용 venv·종목 거래소 정보 (Git 제외)
  research_output/vibe-trading/   날짜별 연구 패킷/분석 결과 (Git 제외)
  reports/paper_lab_v3/           기존 운영 기록, 읽기만 수행
```

## 실행

프로젝트 루트 PowerShell에서:

현재 설치·검증 환경은 Windows Python 3.13이다. 연구 의존성은 별도 venv에
고정하며, 다른 Python 버전에서는 패키지 wheel 호환성을 먼저 확인한다.

```powershell
.\research\vibe_trading\setup.ps1
.\research\vibe_trading\run.ps1 -Through '2026-10-20' `
  -OutputDirectory 'C:\Users\wsr\Desktop\auto-trading\research_output\vibe-trading\20261020-review' `
  -RefreshSymbols
```

출력 경로는 매번 새 경로를 사용한다. `-RefreshSymbols`는 누락 종목의 KOSPI/
KOSDAQ 구분만 Toss에서 읽으며, 이후 캐시가 있으면 생략한다. 연구 환경에는
Toss 인증정보를 복사하지 않는다. 분석 시작 시 외부 키 환경변수를 제거하고
홈 경로를 연구 전용 경로로 설정한다. source ledger는 바꾸지 않는다.

`REPORT.md`: 요약/원장 대조, `vibe_analysis.json`: 실제 upstream 분석 결과,
`summary.json`: Decimal 기반 원장 통계, `evidence.json`: 원장 해시·소스 버전·
정책·시장 맥락, `strategy_contract.json`: 기존 세 전략 설명,
`RESEARCH_TASK.md`: 이 패킷을 근거로 수행할 후속 연구 요청.

고정 revision은 `upstream.json`에 기록한다. 원본이 다르거나 수정됐으면 실행을
거부한다. 설치 환경만 별도이며 강한 OS 샌드박스를 구성한 것은 아니다.
upstream은 현재 정수 6자리 한국 코드만 KRW로 분류하므로, `0167A0` 같은
신규 코드는 검증된 Toss 종목 정보에 한해서 연결 프로세스의 통화 함수를
KRW로 보완한다. 원본 저장소는 수정하지 않는다. upstream market 라벨은
other일 수 있으며, 원화 손익 대조를 통과해야 분석 성공으로 처리한다.

## 결과를 적용하는 기준

### 무료 로컬 연구 확장 (2026-10-22)

`free_research.py`는 고정 upstream의 `compute_ic_series`와
`monte_carlo_test` 계산 함수만 호출한다. 외부 모델/API 호출이나 토큰 과금은
없으며 VM의 CPU/메모리만 사용한다. 주문·설정 변경 기능은 없다.

- 같은 정책 기간의 고유 에피소드를 최초 관측 시점과 정확히 연결한다.
- 거래량/상대 강도와 30분 비용 차감 후 수익률의 순위 상관을 계산한다.
  한 시점에 최소 5종목이 필요하며, 20시점·5일 미만은 표본 부족이다.
- 단일 조건 탈락 후보를 분리하고 최고 1건 제외 결과를 함께 기록한다.
- 계좌별 순손익 순서를 1,000회 섞어 실현 자산 경로를 비교한다.
  총수익은 변하지 않는다. 미래 수익 확률이나 평가손실 포함 최대낙폭이 아니다.
- 겹치는 에피소드는 독립 표본이 아니며, 누락된 관측으로 선택 편향이 있을 수 있다.

Paperclip research 담당이 평일 정상 마감 후 자동 실행한다. 수동 실행:

```powershell
.\research_data\vibe-trading\venv\Scripts\python.exe research/vibe_trading/free_research.py --through 2026-10-22 --output research_output/vibe-trading/free-review-new
```

새 출력 폴더의 `REPORT.md`, `analysis.json`, `episodes.json`을 함께 확인한다.
원장 해시와 upstream revision을 남긴다. 표본 부족을 효과 없음으로 해석하지 않는다.
LLM 전략 생성, 데이터 서비스 구독, 자동 최적화 및 자동 전략 승격은 연결하지 않는다.

연구/예산 계좌는 각각 독립적으로 비교한다. 과거 정책의 거래도 포함되므로
정책 변경일 전후는 날짜별 원장과 함께 해석한다. 현재 통계는 실현손익 기준이며
보유 중 평가손실을 포함한 원장의 최대 평가손실과 구분한다.

Vibe-Trading의 bar 백테스트에 OHLCV만 넣으면 현재 전략의 호가·잔량·거래비용
조건을 재현하지 못한다. 15/30/45분 청산·시장 필터 비교는 원시 tape를 이용한
독립 포트폴리오 재현으로 검증해야 한다. 현재 연결의 journal 분석을 새로운
전략 백테스트로 소개하거나 바로 매수/매도 기준으로 채택하지 않는다.

이번 버전으로 2026-10-20까지 32개 가상 계좌 거래(동일 신호의 양쪽 계좌 거래 포함)를
분석했고, 6계좌 FIFO 손익이 원장과 반올림 오차 범위에서 일치했다.
운영 재개나 GitHub 게시는 이 연구 실행에 포함되지 않는다.
