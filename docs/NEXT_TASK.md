# Next task

Collect paper-only continuation and position-review episodes without changing
thresholds until at least 20 distinct review checkpoints are available.

Compare:

- strict breakout vs continuation entries;
- 5m/10m review outcomes and subsequent 5/10/15/30-minute returns;
- fixed exits vs strong-trend MFE giveback behavior;
- modeled after-cost P&L, MFE, and MAE;
- API/data-unavailable rates.

Do not promote the paper paths to live before at least 50 qualifying episodes,
positive after-cost expectancy, acceptable tail MAE, and a separate live
15:35 force-exit verification.

Separately, validate read-only Toss account, holdings, pending-order,
buying-power, price-limit, and orderbook response shapes in an authorized
environment. The one-share `verify-live-order` command must never be run while
a recurring live process, open order, pending journal, or existing holding for
the symbol is present. Do not enable recurring live orders as part of that
validation.
