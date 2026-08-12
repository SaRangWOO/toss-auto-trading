# Architecture

## 현재 구현

```text
Toss OpenAPI (REST polling)
  -> TossClient: OAuth, throttle/retry, 시세·계좌·주문
  -> TradingEngine.scan: 순위 -> 경고 -> 1분봉 -> 호가 -> 시장 지수
  -> strategy: 모멘텀·거래량·가중 평균·spread 신호
  -> engine risk: 시간·현금·비중·종목 수·일일 guard·stale data
  -> PaperBroker 또는 LiveBroker
       paper: 5bp 불리한 즉시 체결
       live: 매수 limit, 매도 market, 조회·timeout·취소·부분 체결
  -> 포지션: stop·take profit·trailing·15:10 청산·pending 복구
  -> state/*.json + logs/trader.log + report/YYYY/MM/YYYY-MM-DD.md
```

CLI가 설정을 읽고 `once` 또는 `run_forever()`를 실행한다. 주문 전 pending
journal을 저장하고 접수 callback에서 server order ID를 즉시 저장한다.

## 목표와 차이

```text
현재 시작: buying power + 로컬 상태 + pending 1건 복구
목표 시작: 실제 잔고·보유·미체결 조회 -> 실제 계좌 우선 reconcile
          -> 안전 상태가 확인된 뒤 scan/신호/risk/order 허용
```

현재는 수동 보유 종목과 account open orders를 신규 진입에서 피하지만 실제
계좌 상태로 내부 position을 완전히 재구성하지 않는다. 주문 정정, 연속
거래손실 guard, 독립 총 노출 한도, paper/live 별도 로그도 목표 구조와 차이가 있다.
