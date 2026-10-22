# Paperclip × Toss Paper v3

2026-10-21 구성. 내일 2026-10-22 09:00부터 기존 Paper v3 예약 운용을 재개한다.
Paperclip 2026.1012.0은 Windows VM의 별도 Node 의존성 환경에서 실행한다.
화면: http://127.0.0.1:3100 (VM 내부 전용). Linux VM 분리는 아직 적용하지 않았다.

## 실제 연결 범위

- `operations`: 5분 간격 장부/heartbeat 점검. 기존 1분 watchdog은 별도로 유지한다.
- `performance`: 15:45 이후 정상 마감 장부를 Vibe-Trading에 전달하고 손익 대조.
- `research`: 당일 탈락 사유별 관측 횟수와 고유 종목 수 집계. 반복 관측을 독립
  에피소드로 표시하지 않는다. 무료 Vibe 조건별 성과/순위 상관/거래 순서 위험
  분석도 실행한다. 신규 결과는 `research-v2.json`과 `free-vibe-*`에 저장한다.
- `validation`: 두 분석 결과가 준비되면 비용 2배/최고 수익 2건 제외 결과를 확인.
  불리하면 승격 불가, 유리해도 별도 기간 포트폴리오 재현 필요로 판정한다.
  무료 연구 보고서도 연결하며 `validation-v2.json`에 저장한다.
  이전 버전의 당일 결과는 삭제하거나 덮어쓰지 않는다.

담당은 Paperclip `process` 어댑터에 등록된 결정론적 Python 스크립트다.
LLM 모델/유료 AI 호출은 설정하지 않았고, 자율 전략 생성 기능은 포함하지 않는다.
독립 대안 포트폴리오 재현, 전략 변경·배포 자동화는 후속 작업이다.
원본 장부와 매매 코드는 수정하지 않으며 실제 주문 기능은 없다.

Paperclip heartbeat는 각 담당을 300초마다 실행한다. 분석 담당은 15:45 전과
주말에 즉시 종료하고, 성공한 당일 작업은 재사용한다. OS 잠금으로 전체 실행
동시성 2개, 역할별 1개를 제한한다. 정상 마감 확인: 당일 마지막 수집 15:39 이후,
보유 포지션 없음, 당일 일일 보고서 존재. 이는 데이터 품질 합격과 별개다.
미완료/오류는 성공으로 기록하지 않는다. 다음 heartbeat에서 재시도한다.

각 역할은 날짜별 Paperclip 업무에 결과를 연결한다. 운영 경고는 상태가 바뀔 때
갱신하고, 장부 원문·인증정보는 전달하지 않는다. 스크립트 실패는 blocked 상태다.
Paperclip이 중단돼도 매매와 청산은 기존 예약 작업/엔진에서 독립 수행된다.
AI 역할 지시문에 의존하는 보안 격리가 아니라 주문 함수가 없는 고정 스크립트이며,
별도 OS 계정/VM 샌드박스는 아직 구성하지 않았다.

## 위치

- `research/paperclip/`: 연결 코드, 실행/등록 스크립트
- `research_data/paperclip/`: 설치본, DB, 로컬 키와 로그 (Git 제외)
- `research_output/paperclip/YYYY-MM-DD/`: 분석 결과와 업무 연결 상태 (Git 제외)
- `state/paperclip.json`: 회사/담당 ID, `state/paperclip-runtime.json`: Node 경로

## 실행과 예약

`bootstrap.py`는 기동한 로컬 서버에 회사/담당을 등록한다. 반복 실행 시 기존
동일 이름 담당을 갱신한다. 서버가 실행돼야 하며 인증없는 loopback 전용이다.

```powershell
.\.venv\Scripts\python.exe research/paperclip/bootstrap.py
.\research\paperclip\install-task.ps1
Start-ScheduledTask -TaskName TossResearch-Paperclip
```

`TossResearch-Paperclip`: 로그인 시/매일 08:45 기동, 중복 실행 차단,
실패 시 1분 간격 재시작. 실행은 숨김 PowerShell이며 종료 제한 없음.
서버의 자동 DB 백업은 60분 간격, 30일 보관이다. 키/DB 전체 복구에는
`research_data/paperclip/home`도 보존해야 한다. 화면을 외부에 공개하지 않는다.

Windows 예약 작업에는 대화형 터미널의 DLL 경로가 전달되지 않는다.
`native-runtime/`의 Visual C++ 런타임을 서버 PATH에 명시하고 PostgreSQL은
고정 버전 `pg_ctl`로 준비한 후 Node 서버를 시작한다. 두 프로세스는 숨김 창과
파일 리다이렉션으로 실행해 PowerShell 파이프의 자식 프로세스 대기를 피한다.
현재 서버 로그는 `logs/paperclip-current.log`, 오류는 `paperclip-current.err`,
DB 로그는 `paperclip-postgres.log`에 있다.

`TossAutoTrading-Weekdays`: 평일 09:00 `paper-lab-run`.
`TossAutoTrading-DailyReport`: 평일 15:42 `paper-lab-report`.
`TossAutoTrading-Watchdog`: 1분 간격, 장중에만 검사.
모두 2026-10-22 이후로 예약했다. 오늘 장부/위험 상태를 초기화하지 않았다.
현재 작업들은 Interactive 로그인 방식이므로 VM이 켜져 있고 wsr 사용자가
로그인한 상태여야 한다. 화면 잠금은 가능하나 로그아웃 상태 실행은 보장하지 않는다.

## 제한과 해석

Vibe 분석은 누적 청산 거래이며 기존 정책 기간이 섞인다. 당일 보고서와 함께
판독하며, 연구/소액 계좌 손익을 합산해 하나의 포트폴리오로 취급하지 않는다.
단일 조건 완화에 따른 대안 손익, 체결 가능성, 미실현 손실까지 검증하려면
별도의 원시 tape 포트폴리오 재현이 필요하다. 현재 진단 결과만으로 live 전환하지 않는다.

공식 참조: https://github.com/paperclipai/paperclip
https://docs.paperclip.ing/reference/adapters/process/

## 2026-10-22 준비 검증

- Windows 예약 작업에서 실제 서버 기동, `/api/health` 정상.
- 네 process 담당을 서버에서 직접 호출해 모두 succeeded 확인. 장 전 분석 담당은
  outside_analysis_window로 종료하는 것이 정상이며 마감 분석 완료를 뜻하지 않는다.
- 2026-10-20 과거 장부로 Vibe 내보내기/손익 대조 → 탈락 집계 → 검증 전체 실행 성공.
- Paper v3 manifest 일치, paper 모드, 미보유, 전역 entry_halt 없음.
- W32Time Running/Automatic, 지정 서버와 시각 차이는 점검 당시 약 0.49초.
- Interactive 예약이므로 전원과 사용자 로그인을 유지해야 한다.
- 최초 Node 모듈 로딩에 약 90초가 걸려 서버는 매일 08:45에 미리 시작한다.
