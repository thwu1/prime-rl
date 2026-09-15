Produce `/app/twamm_engine.py`, a TWAMM (Time-Weighted Average Market Maker) simulation engine that reads scenario data from a SQLite database and delegates all constant-product AMM pool operations to a provided C library via Python `ctypes` FFI.

**Environment contents to explore:**
- `/app/lib/` — C source and build files for a constant-product AMM pool library. Your engine must compile this into a shared object and call it through `ctypes` for every pool operation (creation, reserve queries, reserve updates). Pure-Python reimplementation of pool state management is not permitted.
- `/app/data/init.sql` — SQL dump defining the database schema and scenario data. Load it into `/app/data/twamm.db` using the `sqlite3` CLI.
- `/app/docs/` — Reference notes on TWAMM mechanics.

**CLI:** `python3 /app/twamm_engine.py <scenario_id>`

**Output** (JSON to stdout):
```json
{
  "final_reserves": {"x": <float>, "y": <float>},
  "order_fills": {"<order_id>": {"received": <float>}, ...}
}
```

**Semantics:** Each scenario references a pool (initial reserves) and a set of orders. Orders specify `sell_token` (`"x"` or `"y"`), `total_sell_amount`, `start_block`, and `end_block`. The sell rate is `total_sell_amount / (end_block - start_block)`. Zero-duration orders (`start_block == end_block`) receive 0 and have no effect on the pool.

TWAMM executes orders as continuous infinitesimal swaps against an embedded CPAMM (x·y=k, no fees). Between consecutive boundary blocks where the active order set changes, the engine must compute the resulting AMM reserve state under simultaneous continuous selling from both sides. Multiple orders selling the same token share the received counter-token proportionally to their sell rates.

**Constraints:**
- All pool state transitions go through the compiled C library via `ctypes`.
- Numeric accuracy: 1e-5 relative tolerance.
- The product invariant x·y=k must hold after each interval.
- Token conservation per token type: `initial_reserve + total_sold = final_reserve + total_received`.
