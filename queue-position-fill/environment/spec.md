# Market Microstructure Fill Simulation Engine — Specification

## Overview

Implement a simulation engine that processes Level-2 market data events,
reconstructs a limit order book, tracks order queue positions under three
queue models, and determines fill outcomes for passive limit orders.

The Rust implementation of the queue position models is at
`/app/reference/queue.rs`. Market data is at `/app/market_data.npz` and
order configuration at `/app/orders.json`.

## 1. Event Data Format

Market data is stored as a numpy `.npz` file with key `"data"`. Each row is a
structured array with dtype:

```
[('ev','u8'), ('exch_ts','i8'), ('local_ts','i8'), ('px','f8'),
 ('qty','f8'), ('order_id','u8'), ('ival','i8'), ('fval','f8')]
```

| Field     | Description                                  |
|-----------|----------------------------------------------|
| ev        | Bitfield of event type flags (see below)     |
| exch_ts   | Exchange timestamp in nanoseconds            |
| local_ts  | Local receipt timestamp in nanoseconds       |
| px        | Price                                        |
| qty       | Quantity (depth level qty or trade size)      |
| order_id  | (unused for L2)                              |
| ival      | (unused)                                     |
| fval      | (unused)                                     |

### Event Flags (bitfield)

| Flag                | Value      | Meaning                              |
|---------------------|------------|--------------------------------------|
| DEPTH_EVENT         | 1          | Depth level update                   |
| TRADE_EVENT         | 2          | Trade execution                      |
| DEPTH_SNAPSHOT_EVENT| 4          | Initial order book snapshot          |
| EXCH_EVENT          | 1 << 31    | Valid at exchange timestamp          |
| LOCAL_EVENT         | 1 << 30    | Valid at local timestamp             |
| BUY_EVENT           | 1 << 29    | Buy side (bid depth or buy aggressor)|
| SELL_EVENT          | 1 << 28    | Sell side (ask depth or sell aggressor)|

**Interpretation:**
- `DEPTH_SNAPSHOT_EVENT | BUY_EVENT`: bid-side initial snapshot level
- `DEPTH_SNAPSHOT_EVENT | SELL_EVENT`: ask-side initial snapshot level
- `DEPTH_EVENT | BUY_EVENT`: bid-side depth update (set qty at price)
- `DEPTH_EVENT | SELL_EVENT`: ask-side depth update (set qty at price)
- `TRADE_EVENT | SELL_EVENT`: sell aggressor trade (hits the bid)
- `TRADE_EVENT | BUY_EVENT`: buy aggressor trade (lifts the ask)

Test a flag with: `(event['ev'] & FLAG) != 0`

## 2. Order Book Reconstruction

Maintain an L2 order book with separate bid and ask sides. Each side maps price
levels to quantities.

- **Snapshot events**: Set quantity at the given price on the indicated side.
- **Depth events**: Set quantity at the given price on the indicated side.
  If qty is 0, **remove** the price level entirely — stale zero-quantity levels
  must not persist, as they would corrupt best-bid/best-ask computation.
- **Trade events**: Do NOT update the order book. Trades are informational for
  queue position models only.

**Best bid** = highest bid price with qty > 0.
**Best ask** = lowest ask price with qty > 0.

When processing a depth/snapshot event, record the **previous quantity** at that
price level before updating. Return `(prev_qty, new_qty)`. For trade events
return `(0.0, 0.0)`.

## 3. Queue Position Models

All models track the estimated quantity ahead of your order in the queue at the
order's price level. Lower values indicate a better queue position and faster
fills.

The Rust implementations are in `/app/reference/queue.rs`. Translate
`RiskAdverseQueueModel`, `ProbQueueModel`, `PowerProbQueueFunc`, and
`LogProbQueueFunc` to Python following the API in Section 8.

### RiskAdverseQueueModel

Conservative model. Queue position starts at the full depth quantity when the
order is placed. Only trades at the order's price advance the position. Depth
decreases clamp the position to the new depth quantity. Depth increases do not
improve the queue position.

### ProbQueueModel

Probabilistic model that estimates what fraction of cancelled volume (depth
decreases beyond traded volume) was ahead vs. behind the order, using a
pluggable probability function. Maintains a cumulative trade quantity tracker
to prevent double-counting trades that have already been reflected in subsequent
depth changes.

Study the `depth()` method in `queue.rs` carefully — the order of operations
for the cumulative trade quantity reset relative to the increase/decrease branch
is critical for correctness.

### Probability Functions

- **PowerProbQueueFunc(n)**: `f(x) = x^n`, `prob = f(back) / (f(back) + f(front))`
- **LogProbQueueFunc**: `f(x) = ln(1+x)`, `prob = f(back) / (f(back) + f(front))`

Return 0.0 when both numerator and denominator are 0.

### Numerical Precision

The `is_filled` method computes executed lots from the queue position.
Rust's `f64::round()` rounds half-values **away from zero** (e.g., 0.5 → 1,
-0.5 → -1), while Python's `round()` uses banker's rounding (half to even).
Your implementation must match the Rust rounding behavior.

## 4. Fill Conditions

For each event, after updating the order book, check active (unfilled, placed)
orders for fills:

**Trade-triggered fills:**
- If a sell-aggressor trade at price P hits a buy order at price P:
  advance queue position via `trade()`, check if filled via `is_filled()`.
- If a buy-aggressor trade at price P hits a sell order at price P:
  advance queue position via `trade()`, check if filled via `is_filled()`.
- If the trade price is **better** than the order price (for buy: sell-aggressor
  trade at px < order price; for sell: buy-aggressor trade at px > order price):
  the order fills immediately without queue tracking.

Check trade-price-improvement before queue advancement for efficiency (a filled
order should not also have its queue state updated).

**Depth-triggered fills (price improvement):**
- If a buy order's price >= current best_ask after a depth update: fill.
- If a sell order's price <= current best_bid after a depth update: fill.

Process depth-based queue updates first, then check for price-improvement fills.

All fills use the **maker fee rate**.

## 5. Order Placement

Orders become active when `exch_ts >= order.submit_time_ns`. At placement:
1. Look up the depth at the **order's specific price level** on the appropriate
   side (NOT the BBO quantity — use `bid_qty_at(price)` or `ask_qty_at(price)`).
2. Initialize queue state with `queue_model.new_order(depth_qty)`.

## 6. Fee Computation

`fee = fill_price * fill_qty * maker_fee_rate`

Negative fee rate = maker rebate (exchange pays you for providing liquidity).

## 7. Required Output

Write `/app/results.json`:

```json
{
  "risk_adverse": {
    "fills": [
      {"order_id": 1, "filled": true, "fill_time_ns": ..., "fill_price": ..., "qty": ..., "fee": ...},
      {"order_id": 2, "filled": false}
    ],
    "position": ...,
    "balance": ...,
    "total_fees": ...
  },
  "prob_power_2": { ... },
  "prob_log": { ... }
}
```

**position** = sum(filled buy qty) - sum(filled sell qty)
**balance** = sum(sell fill values) - sum(buy fill values) - total_fees
**total_fees** = sum of all individual fill fees

## 8. Required Python Module API

`/app/microstructure.py`:

```python
class OrderBook:
    def __init__(self, tick_size: float, lot_size: float): ...
    def process_event(self, event) -> tuple[float, float]: ...
    @property
    def best_bid(self) -> float: ...
    @property
    def best_ask(self) -> float: ...
    @property
    def best_bid_qty(self) -> float: ...
    @property
    def best_ask_qty(self) -> float: ...
    def bid_qty_at(self, price: float) -> float: ...
    def ask_qty_at(self, price: float) -> float: ...

class RiskAdverseQueueModel:
    def __init__(self, lot_size: float): ...
    def new_order(self, depth_qty: float) -> dict: ...
    def trade(self, state: dict, qty: float) -> None: ...
    def depth(self, state: dict, prev_qty: float, new_qty: float) -> None: ...
    def is_filled(self, state: dict) -> float: ...

class ProbQueueModel:
    def __init__(self, lot_size: float, prob_func: callable): ...
    def new_order(self, depth_qty: float) -> dict: ...
    def trade(self, state: dict, qty: float) -> None: ...
    def depth(self, state: dict, prev_qty: float, new_qty: float) -> None: ...
    def is_filled(self, state: dict) -> float: ...

def power_prob_func(n: float) -> callable: ...
def log_prob_func() -> callable: ...
```

`/app/run_simulation.py`:

Run the simulation with three models: `risk_adverse` (RiskAdverseQueueModel),
`prob_power_2` (ProbQueueModel + power_prob_func(2.0)), `prob_log`
(ProbQueueModel + log_prob_func()). Write results to `/app/results.json`.
