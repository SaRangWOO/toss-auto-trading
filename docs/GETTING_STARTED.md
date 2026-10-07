# 처음부터 따라 하는 paper 실행 가이드

대상은 Windows PowerShell 사용자입니다. 모든 명령은 복제한 `auto-trading` 루트에서
실행합니다. 가상환경 활성화는 필요 없습니다. 실제 자금이 없어도 paper 체결을
모사할 수 있지만, 실시간 데이터 연결에는 본인의 Toss OpenAPI 권한이 필요합니다.
API 권한이 없으면 2단계까지 진행하여 오프라인 테스트로 구조를 확인하세요.

## 1. 다운로드와 Python 환경 준비

Git과 Python 3.11 이상을 설치한 후 새 PowerShell을 엽니다.

```powershell
git --version
py -3 --version
git clone https://github.com/SaRangWOO/toss-auto-trading.git auto-trading
cd auto-trading
.\scripts\setup.cmd
```

`py` 명령이 없다면 `python --version`으로 설치를 확인하세요. setup은 `.venv`를
만듭니다. API 인증정보를 생성하거나 Windows 예약 작업을 등록하지 않습니다.
GitHub에 로컬 운영 데이터·인증정보·개발 worktree는 포함되지 않으므로, 새로 복제한
폴더에는 `reports/`, `state/`, `development-worktrees/` 등이 없을 수 있습니다.

## 2. API나 실제 주문 없이 테스트

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

`unittest` 마지막에 `OK`가 표시되면 통과입니다. fake client 기반이므로 테스트에
live 관련 로그가 보여도 실제 주문은 보내지 않습니다. 테스트 개수는 버전에 따라
늘어날 수 있습니다. 문법·공백 검사는 성공 시 출력이 없을 수 있습니다.

## 3. 본인 계정의 paper 연결 설정

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

기존 `.env`가 있다면 덮어쓰지 마세요. 발급받은 Client ID와 Secret을 해당 키에
입력하고, 계좌 식별값은 본인의 API 설정에서 확인해 입력합니다. 파일은 로컬에서만
관리하며 화면 캡처·채팅·GitHub에 공유하지 마세요. 아래 설정은 반드시 유지합니다.

```dotenv
TRADING_MODE=paper
LIVE_TRADING_CONFIRM=
PAPER_PARALLEL_EXPERIMENT=false
```

```powershell
.\scripts\run.cmd check
```

인증 정상과 `거래 모드: paper`를 확인합니다. 이 명령은 인증·계좌·시장 달력을 조회하고
주문하지 않습니다. 출력에 계좌 식별값이 포함될 수 있으므로 외부에 붙여넣지 마세요.
연결이 거부되면 API 권한·허용 IP·로컬 인증 설정을 먼저 확인하세요. live로 바꾸거나
안전 필터를 끄는 방식으로 해결하지 마세요.

## 4. 실행 방식 선택

처음에는 기본 단일 paper를 사용합니다. 이번 병렬 실험을 재현하려면 `.env`의
`PAPER_PARALLEL_EXPERIMENT`만 `true`로 바꾸고 `TRADING_MODE=paper`는 유지하세요.

| 구분 | 단일 paper | 병렬 paper v2 |
| --- | --- | --- |
| 병렬 설정 | false | true |
| 가상 포트폴리오 | 1개 | baseline / continuation / retest 3개 |
| 진입 시간 | `.env`의 ENTRY_WINDOWS | 10:00~11:30 KST |
| 횟수·보유 제한 | `.env` 설정 | 전략마다 일 1회·동시 1개 |
| 기간 | 설정된 runner 운용 | 정상 완료 5거래일 이후 신규 진입 중단 |
| 결과 | 루트 state와 일일 리포트 | reports/parallel_paper_v2 아래 비교 결과 |

```powershell
.\scripts\run.cmd status
.\scripts\run.cmd once
```

최초 status의 “아직 생성된 매매 상태가 없습니다”는 정상입니다. `once`는 한 번만
실행하며, 시간과 조건이 맞으면 **가상 체결**을 생성합니다. 조건 밖이면 거래가 없어도
정상입니다. `scan`은 기본 엔진의 후보 조회이므로 병렬 세 전략 비교를 대신하지 않습니다.

반복 관찰은 아래 명령으로 시작합니다. 병렬 실험의 정상 운용일로 인정받으려면
09:05 이전에 시작해 장 종료까지 유지하세요. 늦게 시작한 날도 기록은 보존하지만
완료 일수에는 포함하지 않습니다. 자세한 공백·오류 기준은
[v2 설명](PARALLEL_PAPER_V2_2026-10-02.md)을 참고하세요.

```powershell
.\scripts\run.cmd run
```

기본 설정상 runner는 15:40에 종료합니다. 자동 실행 예약은 선택 사항입니다.
수동 실행과 예약 실행을 중복해서 시작하지 마세요.

```powershell
.\scripts\install-task.cmd
Get-ScheduledTask | Where-Object { $_.TaskName -like 'TossAutoTrading-*' }
```

설치 스크립트의 권한 요청을 확인하고 등록된 실행 경로·시각을 점검하세요.
PC/VM이 꺼져 있거나 절전 상태면 정상 수집을 보장하지 않습니다. 운영 폴더를 옮기면
기존 예약 경로도 다시 확인해야 합니다.

## 5. 결과 읽기와 종료

```powershell
.\scripts\run.cmd report
```

- `report/YYYY/MM/YYYY-MM-DD.md`: 사람이 읽는 일일 보고서.
- `reports/parallel_paper_v2/comparison.json`: 전략별 거래 수, 비용 차감 손익,
  거래당 손익, 최대 누적 평가손실, 최고 수익 1·2건 제외 성과.
- 같은 폴더의 `trial_progress.json`: 완료 일수와 일별 제외 사유.
- `tapes/`: API 응답과 시점별 재현 기록. 로컬 전용이며 GitHub에 올리지 않습니다.
- 병렬 실행의 루트 상태·일일 보고서는 baseline만 대표합니다. 세 전략을 평가할 때는
  반드시 comparison과 각 전략 폴더를 함께 확인하세요.

긴급 중단은 별도 PowerShell에서 실행합니다.

```powershell
.\scripts\stop.cmd
```

중단은 보유 종목 청산을 보장하지 않습니다. 특히 live에서는 주문·보유 상태를 별도로
확인해야 합니다. 실행 래퍼 `run.cmd`는 status를 포함한 명령 실행 시 watchdog의
pause 파일을 해제하므로, 중단 유지 중에는 무심코 다시 실행하지 마세요.
설정 수정은 runner를 멈춘 상태에서 하세요. 기록 초기화를 위해 `state/`나
`trial_progress.json`을 삭제하지 마세요.

## 자주 만나는 상황

| 현상 | 먼저 확인할 것 |
| --- | --- |
| `No module named toss_trader` | 루트에서 PYTHONPATH를 설정했는지, 지정된 .venv Python인지 |
| 인증/접근 거부 | 본인의 API 사용 권한·허용 IP·인증 설정 |
| 거래 0건 | 휴장 여부, 진입 시간, 필터 탈락 기록; 수익/손실 0은 전략 성공을 뜻하지 않음 |
| 운용일이 증가하지 않음 | trial_progress의 늦은 시작·90초 초과 공백·API/사이클 오류 등 |
| 이미 실행 중이라는 오류 | 기존 runner/예약 작업 확인; 중복 프로세스를 추가하지 않음 |
| 5일 이후 거래 중단 | 실험의 의도된 종료; 결과 검토 없이 상태를 지워 재개하지 않음 |

이 가이드는 paper 검증용입니다. 테스트 통과나 paper 이익만으로 live 안전성·수익성을
보장하지 않습니다. 실제 주문 전환은 별도의 계좌·리스크·검증 검토 대상입니다.
