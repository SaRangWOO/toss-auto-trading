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

Candidates that pass the shadow score are also tracked in
`reports/shadow_tracking/YYYY-MM-DD.json`. The tracker records forward returns at
5, 10, 15 and 30 minutes plus maximum favorable/adverse excursion. These outcomes
are evidence for later threshold review only and never alter the same day's orders.

The initial shadow weights are breakout `0.25`, volume `0.25`, VWAP `0.20`, orderbook `0.15`, trade pressure `0.10`, and market context `0.05`. The minimum shadow score and candidate sample count are configuration values. No threshold is promoted to live automatically.

Position exits use a rolling 20-candle VWAP while the position is open. A VWAP or
breakout failure exit requires two distinct completed candles and corroborating
selling pressure, while the hard stop remains immediate even during the minimum
hold period.

## Paper-only continuation experiment

Following the 2026-08-22 weekly review, paper mode has a conservative auxiliary
morning path for a recent opening-range breakout that remains strong after the
exact crossover candle. It requires two completed candles above the opening
range, a breakout no older than ten minutes, two persistent evaluations, entry
score at least 0.85, volume score at least 0.80, trade-pressure score at least
0.55, order-book score at least 0.50, a positive VWAP distance no greater than
5%, and breakout extension no greater than 1.5%.

This auxiliary path is limited to the first daily entry and still passes all
existing fixed safety, liquidity, market-regime, spread, risk, and final signal
checks. It is never evaluated in live mode. Funnel records include a
`continuation` diagnostic object so rejected cases can be distinguished by
breakout age, opening-range hold/retest, VWAP distance, extension, confirmation
count, and explicit rejection reasons.
