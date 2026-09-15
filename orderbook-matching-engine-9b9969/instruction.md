A reference exchange at `/app/reference/` is the authoritative spec for a price-time-priority limit-order matching engine. Scenarios at `/app/scenarios/*.json` have `input` and `expected_output` keys. Binary wire protocol in `/app/data/FORMAT.md`.

**Required artifacts:**

1. `/app/engine.py` — CLI modes:
   - `engine.py <input.json> <output.json>` — JSON processing
   - `engine.py --binary <input.bin> <output.json>` — RTGX binary input; identical output to JSON mode
   - `engine.py --validate <scenario.json>` — exit 0 if output matches `expected_output`, else 1; print `PASS:` or `FAIL:` to stderr
   - `engine.py --serve <host:port>` — TCP: bind `SO_REUSEADDR`, accept one connection, read RTGX (with magic header) until client half-closes, send JSON result, close, exit
   - `--audit <db_path>` — composable with JSON/binary/serve (may appear before or after mode flag); writes SQLite

2. `/app/Makefile` — six `.PHONY` targets:
   - `process`: JSON mode, `$(INPUT)` `$(OUTPUT)`
   - `replay`: binary mode, `$(INPUT)` `$(OUTPUT)`
   - `validate`: `--validate` each `/app/scenarios/*.json`; exit non-zero if any fail
   - `serve`: start server on `$(HOST):$(PORT)`
   - `audit-summary`: query `$(AUDIT_DB)` via `sqlite3` CLI; tab-separated lines: `total<TAB><N>`, then `<type><TAB><count>` per event type (alphabetical), then `<trader><TAB><position><TAB><balance><TAB><total_fees>` per trader (alphabetical)
   - `filter-events`: `jq` to extract from `$(INPUT)` events with `type == $(EVENT_TYPE)` as JSON array; empty array `[]` when none match

**JSON input:** `{"config": {"maker_fee":float, "taker_fee":float, "tick_size":int, "position_limit":int, "active_order_count_limit":int, "active_volume_limit":int}, "operations":[...]}`
Operations: `{"type":"insert","trader":str,"order_id":int,"side":"BUY"|"SELL","price":int,"volume":int,"lifespan":"GFD"|"FAK"}`, `{"type":"amend","trader":str,"order_id":int,"new_volume":int}`, `{"type":"cancel","trader":str,"order_id":int}`, `{"type":"snapshot"}`.

**JSON output:** `{"events":[...], "accounts":{"<trader>":{"position":int,"balance":int,"total_fees":int}}}`
Balance = cumulative cash: fills debit buyer `price*volume`, credit seller `price*volume`; fees applied per fill (positive=cost, negative=rebate).

**Event schemas** (every object has `"type"`):
- **placed**: `{type, trader, order_id, side, price, remaining}`
- **fill**: `{type, maker, taker, price, volume, maker_fee, taker_fee}`
- **cancelled**: `{type, trader, order_id, remaining_cancelled}`
- **amended**: `{type, trader, order_id, volume_removed}`
- **reject**: `{type, trader, order_id, reason}` — reason: `"active-order-count"` | `"active-volume"` | `"self-cross"`
- **breach**: `{type, trader}`
- **snapshot**: `{type, bids, asks}` — bids descending `[[price,volume],...]`, asks ascending

**Audit SQLite schema:**
- `events(seq INTEGER PRIMARY KEY, type TEXT NOT NULL, data TEXT NOT NULL)` — seq 0-indexed; data is JSON of the event
- `accounts(trader TEXT PRIMARY KEY, position INTEGER NOT NULL, balance INTEGER NOT NULL, total_fees INTEGER NOT NULL)`

**Matching:** Price-time priority, FIFO within level, fills at resting price. Fee per fill: `round(price * volume * rate)`. GFD remainder rests; FAK remainder cancelled immediately (emitting `cancelled` even with zero fills). Rejection checks in order: active_order_count → active_volume → self-cross; first failing emits `reject`. After each fill, check maker then taker: `abs(position) > position_limit` emits `breach` and cancels all that trader's orders in ascending order_id. Cancel/amend on unknown order_id: silently ignored. Amend only decreases; ignored when `new_volume >= total_volume`; if `new_volume < filled`, all remaining removed.
