A directed graph (~50K nodes, ~500K edges) is stored in a SQLite database at `/app/data/graph.db` (table `edges` with integer columns `src`, `dst`). A sequence of 200 batched edge updates is stored as an Apache Parquet file at `/app/data/updates.parquet` (columns: `batch_id`, `src`, `dst`, `diff` where `diff` is +1 for insertion or −1 for deletion; a given edge may appear more than once within a single batch).

A **directed triangle** is an ordered triple `(a, b, c)` of distinct nodes where edges `a→b`, `b→c`, and `a→c` all exist simultaneously.

Create `/app/incremental.py` that:
- Reads the initial graph from the SQLite database and the update stream from the Parquet file
- Computes the directed triangle count for the initial graph and after applying each of the 200 update batches in order
- Writes `/app/results.json`: a JSON array of 201 integers — the triangle count at each step

The solution must finish within 90 seconds for the provided dataset.

Run: `python3 /app/incremental.py`