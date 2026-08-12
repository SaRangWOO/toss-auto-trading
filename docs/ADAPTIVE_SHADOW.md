# Adaptive breakout shadow

Adaptive evaluation runs beside the current live strategy and never creates orders.

The live hard gates remain unchanged: liquidity, leveraged/inverse ETF and ETN exclusions, stale data, spread, buying power, position and daily risk limits, duplicate-order protection, and the current session breakout gate.

For a bounded number of ranked candidates, the shadow evaluator records:

- breakout strength
- intraday volume ratio and percentile-based volume score
- VWAP distance
- order-book imbalance score
- estimated trade pressure from recent trades
- market context
- weighted entry score and rejection reasons

Records are written to `reports/filter_funnel/YYYY-MM-DD.jsonl`. The `trade_pressure` value is an estimate from price relative to the current midpoint; it is not investor identity or institutional flow.

The initial shadow weights are breakout `0.25`, volume `0.25`, VWAP `0.20`, orderbook `0.15`, trade pressure `0.10`, and market context `0.05`. The minimum shadow score and candidate sample count are configuration values. No threshold is promoted to live automatically.
