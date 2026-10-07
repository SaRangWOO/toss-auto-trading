# Paper continuation trial — 2026-09-17 to 2026-09-23

## Scope

Run the continuation-entry experiment in `paper` mode for approximately one
week. No live order path is enabled during this trial.

## Fixed safety gates

- configured entry windows, force exit, and process stop
- fresh market/account data, no pending order, one open position and daily
  entry limit
- liquidity, spread, market-regime, daily-loss, sizing, and risk checks
- positive VWAP distance and bounded 0.5% to 2.0% breakout extension
- two consecutive continuation evaluations within ten minutes of the breakout

## Paper-only signal adjustment

The continuation path retains its adaptive entry and volume scores. It accepts
one of trade-pressure or order-book support rather than requiring both noisy
snapshots. The final signal uses a 1.0x one-minute volume floor and an
institutional-proxy score of two, instead of the normal 1.5x and three.

## Review criteria

Compare continuation-path paper fills with strict-breakout fills and unfilled
shadow candidates. For each continuation entry, review forward 5/10/15/30
minute return, MFE, MAE, exit reason, holding time, and whether the relaxed
component would have admitted an obvious false positive. Do not enable the
paper settings for live orders based only on this one-week result.
