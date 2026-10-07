# 폴더 안내 — 어디서 무엇을 보면 되나요?

## 운영과 개발 구분

`auto-trading/` 자체가 현재 자동매매 운영 본체입니다. 바탕화면의 별도 자동매매
폴더 두 개는 2026-10-07에 아래 개발 공간으로 이동했습니다. 코드 병합이나
브랜치 삭제는 하지 않았으며, 각 브랜치의 이력과 파일을 그대로 보존했습니다.

| 위치 | 용도 | 사용 방법 |
| --- | --- | --- |
| 루트 `scripts/` | 운영 실행·종료·예약 작업 | 자동매매는 이 경로만 사용 |
| 루트 `src/`, `tests/` | 현재 적용된 코드와 테스트 | 현재 기능 확인·수정 |
| `development-worktrees/live-account-sync/` | 실계좌 동기화 개발 브랜치 | 독립적인 변경 검토용, 운영 실행 금지 |
| `development-worktrees/market-regime-adaptive/` | 시장 국면 적응형 전략 개발 브랜치 | 독립적인 변경 검토용, 운영 실행 금지 |

개발 폴더의 이름에 `live`가 있어도 실거래를 켰다는 뜻은 아닙니다.
이번 정리는 운영 모드나 전략을 변경하지 않습니다. 개발 공간에 운영 `.env`를
복사하거나 별도 runner를 실행하지 마세요. 각 공간은 서로 다른 브랜치이므로
파일을 덮어써서 합치지 않습니다. 필요한 기능은 검토와 테스트 후 별도로 통합합니다.

## 결과와 문서 찾기

| 위치 | 내용 |
| --- | --- |
| `README.md` | 프로젝트 소개와 실행 방법 |
| `docs/` | 설계·운영 검토·실험 기준 |
| `report/YYYY/MM/` | 사람이 읽는 날짜별 운영 보고서, Git 보존 |
| `reports/` | 상세 진단·재현용 데이터, 로컬 전용 |
| `reports/parallel_paper_v2/` | 현재 병렬 paper 실험 결과·진행 일수·기록 |
| `logs/` | 실행 과정과 오류 로그 |
| `state/` | 재시작에 필요한 계좌·주문·운영 상태, 임의 삭제 금지 |
| `.env`, `.venv/` | 비밀 설정과 Python 실행 환경, 공유 금지 |

`report/`와 `reports/`는 이름이 비슷하지만 보존 정책과 코드 사용 경로가
다릅니다. 운영에 영향을 주지 않도록 이번에는 이름이나 위치를 바꾸지 않았습니다.

## 이전 경로에서 찾아오기

- 바탕화면 `auto-trading-live-sync` → `auto-trading/development-worktrees/live-account-sync`
- 바탕화면 `auto-trading-regime-adaptive` → `auto-trading/development-worktrees/market-regime-adaptive`

Git의 `worktree move`로 이동하여 저장소 연결도 갱신했습니다. `git worktree list`로
확인할 수 있습니다. 기존 터미널·편집기가 이전 개발 경로를 열고 있었다면 새 경로로
다시 여세요. 이후 이동도 일반 파일 이동 대신 `git worktree move`를 사용하세요.

Windows 예약 작업은 기존 `auto-trading/scripts/` 경로를 그대로 사용합니다.
바탕화면 `project2`는 **Hiworks 출퇴근 자동화**라는 별개 프로젝트여서 이동하지
않았습니다. 자동매매 안에 넣으면 용도가 혼동되므로 별도 유지합니다.
