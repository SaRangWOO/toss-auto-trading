# Entry bottleneck audit — 2026-10-02

Scope: 2026-09-29 through 2026-10-02 morning, local recorded inputs only.
Production strategy and running processes were not changed. Counts below are
repeated observations, not unique opportunities or simulated trades.

Reproduce: `.venv/Scripts/python.exe scripts/audit_entry_bottleneck.py`.
The script reads baseline funnel records and all available compressed tapes;
subsequent records may increase counts. No API calls or account access occur.

## Observed evidence

- Funnel: 8,428 observations; 6,515 with morning continuation diagnostics.
- Entry score rejected 6,511; moving-reference breakout distance rejected 6,486.
- Only 13 observations failed solely on entry score; four were eligible and
  none confirmed. A score reduction alone cannot remove the other failures.
- Raw tape audit: 720 morning ranking cycles, 6,521 orderbook evaluations.
  4,307 of these were below the required KRW 50 billion turnover (about 66%).
  Book evaluations and funnel observations are different populations.
- Recomputed opening-range extension was 0.5–2% for 440 observations. All 440
  failed the implemented distance measured against the preceding running high.
  This is not evidence that all 440 satisfy other conditions or are profitable.
- Breakout-score hold counts: 6,371 zero, 150 one, none two or three.

## Confirmed implementation/design issues

1. `continuation_entry_evaluate` holds price above the opening high but gets
   its distance from adaptive evaluation's last close / preceding running high.
   The promised opening-range extension bound therefore does not implement
   the stated strategy. The four eligible observations were already 4.83%,
   7.06%, 12.14% and 13.73% above the opening high, despite a nominal 2% cap.
2. Adaptive hold scoring compares three closes with a maximum that includes
   the first two candles' own highs. For valid OHLC, those two closes cannot
   exceed that maximum. The three-candle persistence term is unattainable.
3. Confirmation counts scanner evaluations (roughly 30 seconds), not distinct
   completed candles. Three of four eligible observations lost confirmation
   on the next evaluation with unchanged breakout distance/candle reference,
   because transient flow scores changed. The fourth lost the distance and
   score at the next completed candle.
4. Continuation requires both proxies only through a weighted score plus the
   one-proxy gate, and uses instantaneous flow data, not the previously proposed
   rolling average. Independent hard floors and weighted score can still impose
   duplicated pressure.
5. Retest is reached only after the same continuation confirmation. It is not
   an independent pullback entry model; no confirmations means no retest test.
   Both experimental variants are morning-only, unlike the baseline's afternoon
   route. Comparing full-day totals alone confounds strategy and time window.
6. Liquidity filtering is deferred until final analysis. Low-turnover candidates
   consume the bounded adaptive candidate slots before the hard gate. About 66%
   of observed book evaluations are ineligible on turnover alone. Whether later
   ranked names would pass requires a separate coverage analysis.

## Adjacent evaluation limitation

The tape replayer restores the pre-cycle state for a single recorded cycle.
It does not yet simulate a changed strategy's portfolio continuously across
cycles. New hypothetical positions can require price/exit inputs absent from
the historical tape. Missing observations must remain missing, not be replaced
with future prices. Current audit therefore makes no cost-adjusted return claim.

## Recommended correction order

1. Explicitly choose and freeze the reference for an episode: opening range for
   opening breakouts, a separately recorded pre-breakout range for later bases.
   Apply age, extension, hold, and retest to that same reference. No score or
   liquidity threshold reduction is justified by this audit alone.
2. Measure persistence on distinct completed candles above the frozen level;
   use fresh, time-bounded flow samples with documented averaging and reset rules.
3. Apply instrument and liquidity gates before allocating adaptive slots.
4. Give retest its own episode progression and compare matched time windows.
5. Rerun component decisions on saved inputs. For profit evaluation implement
   sequential portfolio replay with explicit missing-data coverage and conservative
   fill/cost handling. Freeze a new version before further forward testing.

Do not claim that corrections guarantee more entries or profit: the reference
correction also rejects extended candidates that the old implementation admitted.
