# Parallel paper v2 — bottleneck correction

This version replaces the active paper trial implementation after the October 2
audit. v1 results are preserved under reports/parallel_paper_v1. v2 starts new,
independent equal-cash portfolios under reports/parallel_paper_v2. Live behavior
is not enabled. As of October 7, the expired October 5 deadline is replaced
by five completed operating business days. All three entry windows are 10:00–11:30 KST.
The baseline retains its legacy entry logic, with the same early liquidity
preselection as the experimental variants for matched candidate coverage.

## Trial coverage policy (2026-10-07)

- Persistent `reports/parallel_paper_v2/trial_progress.json` starts at 0/5;
  old tapes, portfolios and evaluation history are preserved, not credited
  retroactively. `comparison.json.trial` exposes progress and day diagnostics.
- Calendar must confirm today's regular market. Unknown calendar blocks new
  entries and does not count as a holiday or valid day. Confirmed calendar is
  cached in memory per date; a restart checks it again.
- First cycle between 09:00 and 09:05, then continuous cycles through 15:39
  (one-minute tolerance before the 15:40 runner stop), with no gap over 90s.
  Warm-up before 09:00 is ignored. Holidays, late starts, interrupted coverage,
  API/cycle errors and outstanding positions/pending orders do not earn a day.
  Zero trades alone does not disqualify a day. Partial-day paper trades remain
  in evaluation history; coverage is not a claim of profitable performance.
- Count is saved atomically after the tape; restart cannot count a date twice.
  After five valid days, new entries stop in all variants, while exit management
  continues. Live settings, risk limits and strategy signals are unchanged.
- Historical counterfactual sequence replay remains independent of this live
  collection schedule. Archived source hashes include the coverage module.

## Corrected experimental entry rules

- Frozen reference: high of 09:00–09:29 completed bars. Require opening-range
  first/last endpoints, never substitute a rolling recent high. Latest extension
  must be between the existing configured 0.5% and 2% of that reference.
- Episode starts after 09:30 on a close above that level; a subsequent close at
  or below it invalidates the episode. Maximum age remains ten minutes. Opening
  breakouts older than that do not qualify as later intraday bases.
- Persistence: at least two distinct adjacent completed one-minute bars above
  the same level. Repeated scans cannot add confirmation. Score uses up to three
  completed holds. Future and duplicate timestamps cannot add holds.
- Flow: mean of last three independent quote-time samples, at least two samples
  required and observation age no more than 90 seconds. Use only trades with
  timestamps within 90 seconds; quote freshness uses the existing configured
  data-age limit. Permit up to one scan interval of timestamp lead because the
  data call occurs after the cycle timestamp. Missing/invalid data clears flow
  samples. Flow and episode diagnostics are persisted and included in tapes.
- Retest has its own progression: breakout, later bar low within 0.3% of the
  reference while closing above it, then a later close above the preceding
  bar's high. Touch must be among the four bars preceding rebound, within the
  same episode. It never depends on continuation strategy passing first.
- Liquidity and instrument gates precede the bounded adaptive candidate slots.
  Existing turnover, weighted score, volume, proxy thresholds, sizing, daily
  limits and exit rules are retained. Final experimental momentum minima remain
  the previously reviewed zero floors; maxima still apply.

## Replay and evaluation

`python -m toss_trader.experiment --sequence <tape-directory> --output <new-directory>`

Sequential counterfactual replay starts equal paper portfolios once and carries
them across frames. It never overwrites them with later recorded real states.
Old recordings without quotes required by hypothetical positions are flagged;
missing calls caught inside the engine also invalidate the performance claim.
Gaps longer than 90 seconds within one date are recorded. Full-day recordings
are required for closed-trade comparisons. Unclosed final positions also
invalidate the final performance decision. No future quote interpolation.

Replays run current v2 rules even on v1 tape inputs, explicitly as counterfactual
analysis. Single-cycle exact replay still requires the matching source hash.
v2 archives package source under source/<hash> and flow state in each frame.
Metrics exclude only positive winning trades when removing the best one/two;
losing trades are never removed to make a losing sample appear better.

Validation includes fixed-reference extension, three-bar scoring, duplicate and
future bars, repeat scans, stale flow, episode failure, independent retest,
state continuity across replay frames and missing-data invalidation.
