# Weekly entry review plan — 2026-08-22

## Objective

Review the paper-trading and shadow results accumulated through Friday,
2026-08-21, then decide whether the morning entry path should admit a
high-quality continuation after the exact opening-range breakout moment.

Do not weaken fixed safety, liquidity, market-regime, stale-data, leverage and
inverse-product exclusions, position limits, daily-entry limits, or daily-loss
guards.

## Evidence that prompted the review

On 2026-08-20, `002990` was first recorded by the shadow evaluator at 11:03.

- reference price: 14,790 KRW
- adaptive entry score: 0.834
- breakout score: 1.00
- volume score: 0.970; five-minute volume ratio: 5.11
- VWAP score: 1.00; VWAP distance: +4.44%
- trade-pressure score: 0.911
- live session-breakout pass: false
- forward returns: +1.08% at 5m, +2.43% at 10m, +4.39% at 15m,
  +5.41% at 30m
- recorded MFE/MAE over the tracking window: +5.41% / 0.00%

At 11:05 the same symbol had no shadow rejection reason, an entry score of
0.875, order-book score of 0.543, and trade-pressure score of 0.603, but the
live session-breakout gate still returned false. This suggests that the current
boolean gate may be too dependent on catching the exact crossover candle.

This is one episode, not enough evidence by itself to promote a new live rule.

## Candidate change to evaluate

Retain the existing strict breakout path and add a separate continuation path:

1. The opening-range breakout occurred within the prior 5–10 minutes.
2. The latest two completed candles remain above the opening-range high.
3. Adaptive entry score is at least 0.85.
4. Volume score is at least 0.80.
5. Trade-pressure score is at least 0.55.
6. Order-book score is at least 0.50.
7. Price remains above rolling VWAP and no more than 5% above it.
8. Price is no more than approximately 1.5% above the breakout reference, or
   an equivalent ATR-normalized cap is used.
9. The conditions persist across two consecutive evaluations.
10. Existing one-entry-per-session and two-entry-per-day limits remain.

Also add explicit diagnostics for breakout age, completed-candle confirmation,
opening-range retest, VWAP distance, and overextension so a generic
`session_breakout_filter` rejection can be explained.

## Saturday workflow

1. Confirm Friday's process stopped normally and all daily reports were created.
2. Aggregate this week's paper fills, realized P&L, exit reasons, holding times,
   and API/runner errors.
3. Aggregate distinct shadow episodes rather than repeated 30-second records.
4. Compare 5/10/15/30-minute returns and MFE/MAE for shadow-pass episodes.
5. Identify how many positive episodes were blocked only by the strict session
   gate and how many would have been false positives under the candidate rule.
6. If evidence supports the rule, implement it only in paper mode, add detailed
   rejection diagnostics and unit tests, run the full test suite, and leave live
   behavior unchanged.
7. If evidence is insufficient or adverse, preserve the current entry behavior
   and document the reason instead of forcing a strategy change.
8. Report the evidence, decision, code changes, tests, and operating mode.

## Promotion boundary

Saturday's result is a paper-strategy experiment, not permission to enable live
orders. A later live promotion requires a larger set of distinct episodes,
positive after-cost expectancy, acceptable MAE, and separate verification of
the post-close 15:35 force-exit behavior.

## Review result — 2026-08-22

### Operations and reports

- Daily reports exist for every trading day from 2026-08-17 through
  2026-08-21.
- Friday's paper runner started at 09:04:03, stopped at 15:40:03, and the
  daily report task completed at 15:42 with result code 0.
- No `CYCLE_FAILED`, candle API failure, adaptive-data skip, or trader
  warning/error was found in the five daily trader-log slices.
- Launcher failures were concentrated before the runner/watchdog fixes:
  one early report failure on Monday, 341 duplicate/short-lived runner
  failures on Tuesday, and six on Wednesday. Thursday and Friday had none,
  so the corrected runner path remained stable for two consecutive sessions.
- The Windows watchdog task still launches an interactive PowerShell process
  every minute, including outside market hours. It exits immediately when no
  work is due, but this explains the visible window flash and remains a
  separate operations/UI issue.

### Paper trades

| Date | Symbol | Entry | Exit | Exit reason | Holding time | Realized P&L |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| 2026-08-18 | 036930 | 192,996.45 | 194,002.95 | trailing stop | 8m 22s | +1,006.50 KRW |
| 2026-08-21 | 950260 | 19,409.70 | 19,220.385 | breakout/VWAP failure | 3m 00s | -567.945 KRW |

Weekly totals were two round trips, one win and one loss, +438.555 KRW
realized P&L, 50% win rate, 1.772 profit factor, and 5m 41s average holding
time. These are local paper fills with 5 bp adverse execution on each side;
they do not include a full live fee, tax, latency, or market-impact model.

### Distinct shadow episodes

The repeated 30-second observations were collapsed into six symbol/day
episodes. Forward results are measured from each episode's first tracked
reference price.

| Date | Symbol | 5m | 10m | 15m | 30m | MFE | MAE |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-08-19 | 396500 | +0.781% | +0.751% | +1.326% | -0.030% | +1.636% | -0.133% |
| 2026-08-19 | 0167A0 | +0.235% | +0.235% | +0.323% | -0.559% | +1.117% | -1.029% |
| 2026-08-19 | 069500 | +0.034% | +0.396% | -0.218% | -0.430% | +0.498% | -0.744% |
| 2026-08-19 | 102110 | +0.015% | +0.405% | -0.217% | -0.473% | +0.502% | -0.748% |
| 2026-08-20 | 002990 | +1.082% | +2.434% | +4.395% | +5.409% | +5.409% | 0.000% |
| 2026-08-21 | 025980 | -1.678% | -0.839% | -0.671% | -4.698% | +1.342% | -6.040% |

Across all six episodes, average returns were +0.078%, +0.564%, +0.823%,
and -0.130% at 5, 10, 15, and 30 minutes. Only one episode remained positive
at 30 minutes. Average MFE was +1.751% and average MAE was -1.449%. This is
not evidence for a broad relaxation of the session breakout filter.

### Strict-block comparison and decision

The proposed continuation thresholds were replayed against the funnel data:
entry score at least 0.85, volume score at least 0.80, trade pressure at least
0.55, order-book score at least 0.50, price above but within 5% of VWAP,
within 1.5% of the breakout reference, and two adjacent qualifying evaluations.

Only `002990` at 11:05:03 and 11:05:33 met the complete rule. It was blocked
by the strict session gate despite holding above the opening range, and its
30-minute result was +5.409%. None of the five other tracked episodes,
including the -4.698% false-positive episode `025980`, met the complete rule.

This separation supports a tightly bounded paper experiment, but one qualifying
episode is not sufficient for live promotion. The decision is therefore:

1. Keep the strict breakout path as the default.
2. Add the continuation path only when `TRADING_MODE=paper`.
3. Limit it to the morning session and the first daily entry.
4. Require two persistent evaluations and a recent breakout no older than ten
   minutes.
5. Preserve all existing liquidity, market-regime, stale-data, spread,
   buying-power, product, position, daily-entry, and daily-loss guards, plus
   the existing final signal check.
6. Record explicit continuation diagnostics in the funnel log, including
   breakout age, opening-range hold/retest, VWAP distance, breakout distance,
   persistence count, and rejection reasons.

The experiment is enabled in paper mode for the next observation period. Live
behavior is unchanged and no real order was created during this review.

### Verification

- Python compile check: passed.
- Full offline unit suite: 55 tests passed.
- Whitespace/error-marker check: passed.
- Current configured trading mode after the change: `paper`.

Before any live consideration, collect substantially more distinct qualifying
and rejected episodes, compare after-cost expectancy and tail MAE, and verify
the 15:35 forced-exit path independently.
