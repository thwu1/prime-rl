# Exchange Matching Engine Specification

## Order Types

### LIMIT
Standard limit order. Matches against contra-side orders at the limit price or better. Unfilled remainder rests in the order book.

### IOC (Immediate-or-Cancel)
Matches against resting orders at the limit price or better. Any unfilled quantity is immediately cancelled and **never rests in the book**.

### FOK (Fill-or-Kill)
All-or-nothing execution. Before matching, the engine verifies that sufficient contra-side liquidity exists at the limit price or better. Available liquidity for each resting order includes both the visible `remaining` **and** `hidden_qty` (for iceberg orders). Self-trade candidates (same `trader_id`) are excluded from the liquidity count.

If available liquidity is less than the order quantity, the order is **rejected** with zero fills and no book changes. Otherwise, the order matches normally.

### ICEBERG
An order with a visible display portion and a hidden reserve.

**Initialization:**
- `remaining` = `display_qty` (the visible tranche size)
- `hidden_qty` = `quantity - display_qty` (the hidden reserve)

**Resting iceberg replenishment:** When a resting iceberg's display portion is fully consumed during matching (`remaining` reaches 0) and `hidden_qty > 0`:
1. Replenish: `remaining = min(display_qty, hidden_qty)`, then `hidden_qty -= remaining`
2. The order moves to the **BACK** of its price level queue (loses time priority)
3. Matching continues with the next order in the queue

**Aggressive iceberg replenishment:** When an incoming iceberg order's display portion is fully consumed during matching (`remaining` reaches 0) and `hidden_qty > 0`:
1. Replenish: `remaining = min(display_qty, hidden_qty)`, then `hidden_qty -= remaining`
2. Continue matching against the book with the replenished display
3. This allows an aggressive iceberg to fill up to its full quantity across multiple display tranches

When both `remaining` and `hidden_qty` are 0, the order is fully filled and removed.

## Matching Rules

### Price-Time Priority
- Buy orders match against asks, starting from the lowest ask price
- Sell orders match against bids, starting from the highest bid price
- At the same price level, orders are matched in FIFO order

### Self-Trade Prevention
When an incoming order would match against a resting order from the same `trader_id`, the resting order is cancelled (removed from book) and the incoming order continues matching.

### Fill Quantity
Each fill quantity is `min(incoming_order.remaining, resting_order.remaining)`.

### Trade Record
Each fill generates a Trade with:
- `trade_id`: monotonically increasing counter
- `buy_order_id`, `sell_order_id`: the two matched order IDs
- `price`: the resting order's price level
- `quantity`: the fill size
- `timestamp`: the aggressive (incoming) order's timestamp

## Market Data Feed

The `MarketDataFeed` class must implement two methods that append entries to `self.entries`:

### `record_event(book, trades, aggressor_side, timestamp)`
Called after processing each NEW_ORDER event.

For each trade in the trades list, append a trade tick:
```
{"type": "TRADE", "trade_id": N, "price": "<decimal_as_str>", "quantity": N, "aggressor_side": "BUY"|"SELL", "timestamp": N}
```

Then append exactly one BBO update:
```
{"type": "BBO", "best_bid_price": "<decimal_as_str>"|null, "best_bid_qty": N, "best_ask_price": "<decimal_as_str>"|null, "best_ask_qty": N, "timestamp": N}
```

### `record_cancel(book, timestamp)`
Called after processing each CANCEL event. Append one BBO update (same format).

### BBO Quantity
The BBO quantity is the sum of `remaining` (visible) quantity at the best price level. Hidden iceberg quantities are **NOT** included in BBO qty.

## Snapshot Format

JSON file containing:
- `last_seq`: sequence number of the last event included
- `trade_counter`: current trade ID counter value
- `bids`: dict mapping price strings to lists of serialized orders
- `asks`: dict mapping price strings to lists of serialized orders

Each serialized order must include **all** fields: `order_id`, `trader_id`, `side`, `price` (as **string**, not float), `quantity`, `remaining`, `timestamp`, `order_type`, `display_qty`, `hidden_qty`.

## Replay Invariants

- Events with `seq <= last_seq` must be skipped (the snapshot already includes their effects)
- Replay must construct Order objects with correct initialization:
  - For ICEBERG: `remaining = display_qty`, `hidden_qty = quantity - display_qty`
  - For other types: `remaining = quantity`, `hidden_qty = 0`
  - `order_type` must be read from the event
- After replay, the order book state hash must be identical to live processing
