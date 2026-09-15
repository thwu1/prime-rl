Build `/app/pool_tool.py` — a CLI that operates on pool-encoded persistent vector collections.

## Environment

`/app/pools/` — Four pool files in an undocumented JSON encoding. Each represents a set of persistent vectors that may share internal tree structure, with varying encoding parameters and tree depths.

`/app/oracle.db` — SQLite database (table `oracle`: columns `pool_file`, `vector_index`, `reconstructed`) containing verified element arrays for selected vectors.

`/app/pool_ref` — Reference binary accepting a pool file path, printing reconstructed vectors as a JSON array of arrays.

No format specification is provided. Reverse-engineer the encoding from pool files, oracle entries, and reference binary output.

## Subcommands

**`reconstruct <pool.json>`** — Decode all vectors in the pool. Print as JSON array of arrays to stdout.

**`sharing <pool.json>`** — For each node in the pool, determine which vectors reference it (directly or transitively). Output JSON with `"leaves"` and `"inners"` keys, each mapping node ID (string) to a sorted list of vector indices.

**`transform <pool.json> <expr> -o <output.json>`** — Apply a Python expression (`x` bound to each element) to every element value. Write a new pool JSON preserving exact internal topology with only leaf values changed.

**`diff <pool.json> <idx1> <idx2>`** — Compare two same-size vectors from the pool. Output JSON with `"changes"` (array of `{"index", "old", "new"}`) and `"stats"` containing `"elements_compared"`, `"elements_skipped"`, `"total_elements"`. Must be structure-aware: when both vectors reference the same internal node at a position, skip that entire region without examining elements.

**`merge <pool1.json> <pool2.json> -o <output.json>`** — Combine two pools with matching encoding parameters. Pool1 vectors appear first. Nodes structurally identical across inputs must be deduplicated to the minimum distinct set. Structural identity is recursive: two nodes match when their stored data and all descendants match, regardless of original IDs. Output uses contiguous integer IDs starting from 0 per category (leaves and inners have separate ID spaces). Assign IDs by processing pool1 entries before pool2.