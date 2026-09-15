# Queue Position Fill Simulator — Specification

## Event Data Format

Events are stored as a numpy structured array with dtype:

```python
event_dtype = np.dtype([
    ('ev',       '<u8'),   # Event type flags (uint64)
    ('exch_ts',  '<i8'),   # Exchange timestamp in nanoseconds (int64)
    ('local_ts', '<i8'),   # Local timestamp in nanoseconds (int64)
    ('px',       '<f8'),   # Price (float64)
    ('qty',      '<f8'),   # Quantity (float64); 0 means level removed
    ('order_id', '<u8'),   # Order/trade ID (uint64)
    ('ival',     '<i8'),   # Integer metadata (unused, int64)
    ('fval',     '<f8'),   # Float metadata (unused, float64)
], align=True)
```

Load with: `events = np.load('/app/data/events.npz')['events']`

## Event Type Flags

The `ev` field is a bitmask composed of a base type in the lower bits and modifier flags in higher bits:

| Constant              | Value      | Description |
|-----------------------|------------|-------------|
| `DEPTH_EVENT`         | `1`        | Incremental depth update at a price level |
| `TRADE_EVENT`         | `2`        | A trade occurred |
| `DEPTH_CLEAR_EVENT`   | `3`        | Clear all depth on one side |
| `DEPTH_SNAPSHOT_EVENT` | `4`       | Depth snapshot entry |
| `BUY_EVENT`           | `1 << 29`  | Buy side (bid depth, or buyer-initiated trade) |
| `SELL_EVENT`          | `1 << 28`  | Sell side (ask depth, or seller-initiated trade) |
| `EXCH_EVENT`          | `1 << 31`  | Exchange-sourced event |
| `LOCAL_EVENT`         | `1 << 30`  | Local-sourced event |

Extract the base type: `base_type = int(ev) & 0xF`

Check a flag: `has_flag = (int(ev) & FLAG) != 0`

Events in the data have both `EXCH_EVENT` and `LOCAL_EVENT` set. The key distinctions are:
- `DEPTH_CLEAR_EVENT | BUY_EVENT`: Clear all bid levels
- `DEPTH_CLEAR_EVENT | SELL_EVENT`: Clear all ask levels
- `DEPTH_SNAPSHOT_EVENT | BUY_EVENT`: Snapshot bid level (set qty at price)
- `DEPTH_SNAPSHOT_EVENT | SELL_EVENT`: Snapshot ask level
- `DEPTH_EVENT | BUY_EVENT`: Incremental bid depth update
- `DEPTH_EVENT | SELL_EVENT`: Incremental ask depth update
- `TRADE_EVENT | BUY_EVENT`: Buyer-initiated trade (lifts asks)
- `TRADE_EVENT | SELL_EVENT`: Seller-initiated trade (hits bids)

## Order Book Reconstruction

Process events in array order to maintain an L2 order book:

1. **DEPTH_CLEAR**: Remove all levels on the indicated side.
2. **DEPTH_SNAPSHOT**: Set the quantity at the given price level. Applied after clears to establish initial state.
3. **DEPTH_EVENT**: Update the quantity at a price level. If `qty == 0`, the level is removed.
4. **TRADE_EVENT**: Indicates a trade occurred at the given price. Trades do NOT directly update the order book — subsequent depth events reflect the post-trade quantity.

Convert price to tick: `price_tick = int(round(px / tick_size))`

## Queue Position Models

### Overview

When a limit order is placed, all existing quantity at that price level is ahead in the queue. As trades and cancellations occur, the queue position evolves. Different models estimate how cancellations affect the queue differently.

### Order Placement

When an order is placed at a price level:
- `front_q_qty` = current book quantity at that level (all existing orders are ahead)
- For ProbQueueModel variants: `cum_trade_qty = 0`

### 1. RiskAdverseQueueModel

The most conservative model. Queue position advances only when trades consume orders ahead.

**trade(qty):**
```
front_q_qty -= qty
```

**depth(prev_qty, new_qty):**
```
front_q_qty = min(front_q_qty, new_qty)
```

No cumulative trade tracking. Cancellations are assumed to occur behind the order (worst case).

### 2. ProbQueueModel

Uses a probability function to estimate what fraction of depth decreases (from cancellations) occurred ahead vs. behind the order. Tracks cumulative trade quantity to avoid double-counting trade-induced depth changes.

**trade(qty):**
```
front_q_qty -= qty
cum_trade_qty += qty
```

**depth(prev_qty, new_qty):**
```
chg = prev_qty - new_qty
chg -= cum_trade_qty          # Subtract trades already accounted for
cum_trade_qty = 0              # Reset after accounting

if chg < 0:                    # Quantity increased (new orders added)
    front_q_qty = min(front_q_qty, new_qty)
    return

# chg > 0: net cancellations occurred
front = front_q_qty
back = prev_qty - front

prob = probability_function(front, back)    # Probability cancellation was behind
if prob is infinite:
    prob = 1.0

est_front = front - (1 - prob) * chg + min(back - prob * chg, 0)
front_q_qty = min(est_front, new_qty)
```

The `min(back - prob * chg, 0)` term handles the case where the estimated behind-cancellation exceeds the behind-queue quantity, attributing the excess to the front.

`prev_qty` is the book quantity at the price level **before** the current depth event is applied. This is the value stored in your order book tracker, which is only updated by depth events (not trades).

### Probability Functions

All take `(front, back)` and return the probability that a cancellation came from behind the order:

| Name | Formula |
|------|---------|
| `PowerProbQueueFunc(n)` | `back^n / (back^n + front^n)` |
| `LogProbQueueFunc` | `ln(1+back) / (ln(1+back) + ln(1+front))` |
| `LogProbQueueFunc2` | `ln(1+back) / ln(1+back+front)` |
| `PowerProbQueueFunc3(n)` | `1 - (front / (front+back))^n` |

Handle division by zero: if the denominator is zero, return 0.

### Fill Detection

After each trade or depth event at the order's price level, check:

```
exec_lots = round(-front_q_qty / lot_size)     # Python round(), not floor
if exec_lots > 0:
    ORDER IS FILLED
    front_q_qty = 0    # Reset after fill
```

### Trade-Through Fills

A trade-through occurs when a trade executes at a price better than the order's price, meaning the order would have been filled regardless of queue position:

- **Buy order at price_tick P**: If a `SELL_EVENT` trade occurs at price_tick < P, the order is filled.
- **Sell order at price_tick P**: If a `BUY_EVENT` trade occurs at price_tick > P, the order is filled.

Trade-through fills apply to all models simultaneously.

## Required Models

Implement these five models with these exact names:

| Key Name | Model |
|----------|-------|
| `risk_adverse` | RiskAdverseQueueModel |
| `power_prob_n2` | ProbQueueModel with PowerProbQueueFunc(n=2) |
| `log_prob` | ProbQueueModel with LogProbQueueFunc |
| `log_prob2` | ProbQueueModel with LogProbQueueFunc2 |
| `power_prob3_n3` | ProbQueueModel with PowerProbQueueFunc3(n=3) |

## Input Files

- `/app/data/events.npz`: Market events. Load as `np.load(...)['events']`.
- `/app/data/orders.json`: Array of order objects:
  ```json
  {
    "id": 1,
    "side": "buy",
    "price_tick": 499999,
    "qty": 0.1,
    "place_at_ts": 1000000123456
  }
  ```
  Place each order when processing the first event with `exch_ts >= place_at_ts`. At placement, read the current book quantity at the order's price level.
- `/app/data/config.json`: `{"tick_size": 0.1, "lot_size": 0.001, ...}`

## Output Format

Write `/app/results.json` with this exact structure:

```json
{
  "orders": [
    {
      "order_id": 1,
      "side": "buy",
      "price_tick": 499999,
      "qty": 0.1,
      "models": {
        "risk_adverse": {
          "filled": true,
          "fill_event_idx": 342,
          "fill_exch_ts": 1000001234567,
          "final_front_q_qty": 0.0
        },
        "power_prob_n2": {
          "filled": false,
          "fill_event_idx": null,
          "fill_exch_ts": null,
          "final_front_q_qty": 2.345
        }
      }
    }
  ],
  "book_state": {
    "final_best_bid_tick": 499998,
    "final_best_ask_tick": 500001,
    "final_best_bid_qty": 3.456,
    "final_best_ask_qty": 1.234,
    "total_trade_events": 892,
    "total_depth_events": 2108
  }
}
```

- `fill_event_idx`: 0-based index into the events array where the fill occurred, or null
- `fill_exch_ts`: Exchange timestamp at fill, or null
- `final_front_q_qty`: Rounded to 6 decimal places
- `final_best_bid_qty` / `final_best_ask_qty`: Rounded to 6 decimal places
- Orders must appear in the same order as in `orders.json`
- Model keys must match the exact names in the table above
