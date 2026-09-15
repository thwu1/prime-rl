Binary market data feed files in `/app/feeds/` use a custom binary format with a variable-length metadata header followed by MBO (market-by-order) records. Format documentation is at `/app/docs/`. A symbology mapping at `/app/symbology.json` and checkpoint timestamps at `/app/checkpoints.json` are also provided.

`/app/symbology.json` schema:
```json
{"mappings": [{"canonical": "SYM", "venues": {"VENUE_NAME": <instrument_id>, ...}}, ...]}
```

`/app/checkpoints.json` — flat array of nanosecond-epoch timestamps.

Create an executable `/app/reconcile` that reads all `.bin` files from `/app/feeds/`, merges order events across venues using the symbology mapping, and writes two output files:

**`/app/output/snapshots.json`** — Consolidated book state at each checkpoint:
```json
[{"timestamp": <u64_ns>, "books": {"<SYMBOL>": {"bids": [{"price": <float>, "size": <int>, "count": <int>}], "asks": [...]}}}]
```
Top 5 price levels per side, aggregated by price. Bids descending, asks ascending. `count` = number of distinct orders at that price. Omit symbols with empty books (no orders on either side). Snapshot captures state after processing all events with `ts_event` <= checkpoint timestamp.

**`/app/output/anomalies.json`** — Detected anomalies, sorted by timestamp:
```json
[{"type": "<type>", "timestamp": <u64_ns>, ...}]
```

Anomaly types with required fields:
- `sequence_gap`: `venue` (dataset name from file header), `expected_seq`, `actual_seq`. Per-venue monotonic gaps in record sequence numbers.
- `phantom_order`: `venue`, `order_id`. Cancel or Fill referencing an order_id with no prior Add or Modify on any venue.
- `duplicate_trade`: `symbol` (canonical), `price` (float), `size`. Trade actions from different venues for the same instrument with identical `ts_event`, price, and size.
- `crossed_book`: `symbol`, `best_bid` (float), `best_ask` (float). First event causing consolidated best bid >= best ask for each instrument.

Event processing rules: order by `ts_event`; same-timestamp events from different venues are independent. Add inserts an order. Cancel removes an order. Modify updates an existing order's price/size; if the order is unknown, treat it as an Add. Fill reduces order size; remove the order when size reaches zero. Trade is informational only and does not modify the book. Clear removes all orders for that instrument.
