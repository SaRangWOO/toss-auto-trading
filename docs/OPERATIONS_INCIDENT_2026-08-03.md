# Operations Incident: 2026-08-03

## Finding

The weekday scheduled task started at 09:04 but its child process stopped after
the 09:43:10 cycle. Task Scheduler reported exit code `1`, and the task was
`Ready` rather than running. There was no `AUTO_TRADING_STOP` or
`DAILY_REPORT_FAILED` event, so the engine never reached its 15:20 shutdown and
report path. The saved state had no position and no pending order.

The exact original exception cannot be recovered because the PowerShell wrapper
discarded the child process stdout/stderr. The failure was therefore classified
as an unobserved process/launcher failure, not a strategy halt.

## Remediation

- `scripts/run.ps1` now appends launcher start, exit code, and PowerShell fatal
  errors to `logs/launcher.log`, while preserving child output.
- Unexpected top-level Python exceptions are written to `logs/trader.log` as
  `CLI_FATAL` before returning exit code 1.
- The weekday task now retries failed runs up to three times at one-minute
  intervals.
- `TossAutoTrading-DailyReport` runs at 15:25 on weekdays as an independent
  report fallback.
- `scripts/stop.ps1` stops both scheduled tasks.

The scheduled tasks were re-registered after these changes. The missing report
for today was generated manually after close using read-only account/order API
queries.

## Follow-up on 2026-08-04

The first version of the new PowerShell capture pipeline treated Python's
normal stderr logging as a terminating PowerShell error under
`$ErrorActionPreference = "Stop"`. This caused the 09:04 run to exit at
startup. The wrapper now captures stdout and stderr separately and evaluates
the Python process by its exit code. A manual restart was verified as
`Running`, with repeated cycles and no pending order or position.
