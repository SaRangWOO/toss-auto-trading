# Architecture

## Current flow

```text
Toss OpenAPI (REST polling)
  -> TossClient: OAuth, throttling/retry, market/account/order APIs
  -> live startup reconciliation: holdings + pending orders + buying power
  -> TradingEngine.scan: ranking -> warnings -> candles -> orderbook -> market regime
  -> strategy: fixed safety -> liquidity -> breakout/adaptive proxy scores
  -> engine risk: time, cash, exposure, daily guards, stale data
  -> PaperBroker or LiveBroker
       paper: adverse slippage + modeled commission/sell tax
       live: marketable-limit buy, market risk exit, timeout/cancel/partial fill
  -> position: hard/failure exits + paper-only 5m/10m review and profit protection
  -> state/*.json + logs/trader.log + report/YYYY/MM/YYYY-MM-DD.md
```

CLI loads configuration and runs one cycle, the recurring runner, reporting, or
the separately gated one-share live verification command. Orders are journaled
before submission and the server order ID is saved by the submission callback.

## Live account truth

At live startup, `TradingEngine` reads holdings, pending orders, and buying
power. `reconciliation.py` applies account truth to `PortfolioState` before new
entry scanning is allowed. Clean synchronization is `SUCCEEDED`; discrepancies
are `DEGRADED`; query errors are `FAILED`. Any non-success state blocks new live
entries while preserving existing risk exits.

## Paper experiments

The continuation entry and 5m/10m position-management paths are evaluated only
when `TRADING_MODE=paper`. They do not relax live startup reconciliation, fixed
safety, liquidity, stale-data, position, daily-entry, or daily-loss guards.

## External research path

```text
KIS read-only minute/flow APIs or normalized licensed CSV
  -> research.py chronological replay
  -> strict / Stock-in-Play / retest / flow-confirmed comparison
  -> next-bar-open execution + modeled round-trip costs
  -> development/evaluation report in research_output/
  -> paper experiment candidate only (never automatic live promotion)
```

The research path is not imported by the recurring trading engine. KIS credentials
cannot place orders because the client implements quotation endpoints only. Raw
research datasets and generated results remain local and are ignored by Git.

## Remaining gaps

Toss response schemas, account permissions, actual fees/taxes, live forced exit,
and the one-share verification flow still require an explicitly authorized real
environment. Order amendment, independent total portfolio exposure, consecutive
trade-loss guard, and remote alert/kill switch remain unimplemented.
