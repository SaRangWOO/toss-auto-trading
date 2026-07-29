# Next task

Validate the read-only account, holdings, pending-order, buying-power, price-limit, and orderbook response shapes in a Toss paper or otherwise authorized environment. Confirm the production order schema and account permissions, then perform one approved one-share verification order and reconcile its order/holding state before resuming automation.

Command shape:

```powershell
.\scripts\run.cmd verify-live-order --symbol 090710 --quantity 1 --side BUY --order-type LIMIT --price-source BEST_ASK --no-retry --confirm LIVE-ORDER-090710-1
```

Do not run this while any recurring live process, scheduled task, open order, pending journal, or existing holding for `090710` is present. If the command reports `ORDER_STATUS_UNKNOWN`, do not rerun it; reconcile the order by `clientOrderId`/`orderId` first.

Do not enable live orders as part of this validation.
