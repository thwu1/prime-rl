Build a limit order book matching engine in C, delivered as a POSIX shared library and a command-line binary.

**Artifacts (all produced by `make -C /app`):**
- `/app/libengine.so` — position-independent shared library implementing the API in `/app/include/engine_api.h`
- `/app/engine` — CLI binary dynamically linked against `libengine.so`

**CLI usage:** `/app/engine <input_file> <output_file>`

**Provided:** `/app/include/protocol.h`, `/app/include/types.h`, `/app/include/engine_api.h`, `/app/Makefile` (skeleton).

## Binary Message Format

Little-endian unsigned integers. Each message: 1-byte type code + payload.

| Type | Payload | Fields |
|------|---------|--------|
| `A` (Add) | 25 B | `order_id`:u64, `side`:u8 (0=buy,1=sell), `qty`:u32, `price`:u32, `trader_id`:u64 |
| `X` (Cancel) | 8 B | `order_id`:u64 — remove; ignore if absent |
| `D` (Reduce) | 12 B | `order_id`:u64, `reduce_qty`:u32 — decrease qty; remove if reaches zero or exceeds remaining; ignore if absent |
| `U` (Replace) | 24 B | `old_id`:u64, `new_id`:u64, `new_qty`:u32, `new_price`:u32 — atomically remove old, submit new inheriting side/trader_id with fresh time priority; may match immediately; ignore if old_id absent |
| `Q` (Query) | 17 B | `query_id`:u64, `query_type`:u8, `param`:u64 |

Prices in hundredths (10050 = $100.50), range [1, 10 000 000].

## Matching Rules

Price-time priority. Buys sorted descending by price, then ascending by arrival. Sells ascending by price, then ascending by arrival. A buy crosses when price >= best offer; a sell when price <= best bid. Execution at resting order's price. Sweeps through multiple price levels. Self-trade prevention: skip resting orders with the same `trader_id` and continue matching.

## Output

Executions: `E <buy_oid> <sell_oid> <price> <qty>`
Queries: `Q <query_id> <result>` — type 0: best bid price or `0`; type 1: best offer price or `0`; type 2: total resting volume at price `param`; type 3: `<buy_levels> <sell_levels>`; type 4: `<side> <price> <qty>` or `NONE`.

## Shared Library Constraints

Every function declared in `/app/include/engine_api.h` must be implemented in `libengine.so`. Each `lob_book` instance must be fully independent — no shared mutable global state between instances. Multiple books created concurrently must operate correctly in isolation. Only symbols prefixed with `lob_` may appear as exported functions in the dynamic symbol table of `libengine.so`.

The CLI binary must process 500 000 messages within 30 seconds.
