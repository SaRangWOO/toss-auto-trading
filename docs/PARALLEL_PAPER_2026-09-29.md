# Parallel paper trial v1

Trial entry dates: 2026-09-29 through 2026-10-05 KST. After that date the
experiment accepts no new entries; existing positions remain managed. No live
promotion is automatic. Historical reports remain intact.

Three independent paper portfolios start at the configured paper balance.
Baseline retains the deployed strategy. Continuation requires two confirmed
evaluations and replaces the duplicated 5/15-minute positive momentum minima
with zero; upper momentum bounds, liquidity, spread, VWAP, daily-change and risk
rules remain. Retest additionally requires one of the preceding four completed
bars to touch within 0.3% of the opening high and close above it, followed by a
higher latest close. Both variants remain morning-only, consistent with the
existing continuation evaluator. All variants use identical costs and exits,
one position and one entry per day. No backfilled trades are invented.

Outputs under reports/parallel_paper_v1/<variant>: persistent portfolio state,
evaluation.jsonl, summary.json, signal diagnostics and existing shadow logs.
The ordinary status/report shows baseline only. Evaluation records equity each
cycle, cost-adjusted realized P&L for closed positions, maximum marked equity
drawdown, net per trade, results excluding the best one/two trades, daily P&L
and error counts. Missing price samples and sampling frequency limit drawdown
precision; immediate paper fills do not simulate exchange queue priority.

MarketTape caches identical read requests within a cycle and denies account and
order API methods. Calls made at different moments are not an atomic exchange
snapshot. Compressed tapes include actual inputs, pre-cycle portfolios,
confirmation state and secret-free settings. Replay uses no network:

    python -m toss_trader.experiment --replay <cycle.json.gz> --output <new-directory>

Replay reproduces that cycle using the saved state; use the same source version.
Missing inputs fail closed. Random paper order IDs may differ. Older data without
raw snapshots cannot be reconstructed exactly and is not counted as trial fills.

Decision: reject a relaxation if its incremental trades have negative net P&L;
hold if profits disappear after removing the best trades or concentrate in one
day. With zero trades, results are undefined, not a successful strategy. Compare
eligible-time decisions, not the earlier shadow observation price. Inspect final
signal reasons and measured values before changing any threshold.
