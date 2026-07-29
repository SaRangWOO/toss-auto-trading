# Project state

`feat/live-account-state-sync` adds startup reconciliation for live mode.

- Account holdings, pending orders, and buying power are queried before strategy entry.
- Broker state is authoritative for quantity, cash, and recovered holdings.
- Clean synchronization is `SUCCEEDED`; discrepancies are `DEGRADED`; query errors are `FAILED`.
- `DEGRADED`, `FAILED`, `NOT_STARTED`, and `IN_PROGRESS` block new entries. Existing exit/risk logic remains available.
- Discrepancy reasons are persisted in `recovery_required` and `sync_reason` for crash-window and operator review.
- This change is validated with fake clients and does not call Toss during tests.

The Toss response schema still needs validation in a real authorized environment. No live order was submitted by this work.
