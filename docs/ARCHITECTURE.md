# Architecture note

At live startup, `TradingEngine` calls `holdings()`, `pending_orders()`, and `buying_power()`. `reconciliation.py` parses the responses and applies account truth to `PortfolioState` before `run_once` can scan for entries.

Local-only positions are removed because the account no longer confirms them. Account-only positions are recovered with their average price and force `DEGRADED`. Pending orders are persisted for crash-window visibility and also force `DEGRADED`. A clean read and comparison produces `SUCCEEDED` and permits the existing strategy to enter. No strategy threshold, order type, paper fill rule, or live broker order flow was changed.
