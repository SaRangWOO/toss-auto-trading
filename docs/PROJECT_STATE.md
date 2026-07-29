# Project state

`feat/live-account-state-sync` adds startup reconciliation for live mode.

- Account holdings, pending orders, and buying power are queried before strategy entry.
- Broker state is authoritative for quantity, cash, and recovered holdings.
- Clean synchronization is `SUCCEEDED`; discrepancies are `DEGRADED`; query errors are `FAILED`.
- `DEGRADED`, `FAILED`, `NOT_STARTED`, and `IN_PROGRESS` block new entries. Existing exit/risk logic remains available.
- Discrepancy reasons are persisted in `recovery_required` and `sync_reason` for crash-window and operator review.
- Order failures now preserve decoded Toss error code/message/data/request ID, journal the request before submission, block the affected symbol or account, and avoid blind 422 retries.
- A separate `verify-live-order` command supports exactly one `BUY LIMIT` share at `BEST_ASK`; it requires `TRADING_MODE=live`, the exact confirmation string, `--no-retry`, clean account/pending state, and successful read-only preflight. It does not invoke strategy scanning or the recurring runner.
- This change is validated with fake clients and does not call Toss during tests.

The Toss response schema still needs validation in a real authorized environment. No live order was submitted by this work. A minimum one-share order must be performed separately only after the decoded error path and account permissions are confirmed.
