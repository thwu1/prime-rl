Build a cost-based query optimizer that reads catalog statistics from a SQLite database, considers multiple physical operators, and produces optimal execution plans with graphviz visualizations for star-schema queries.

`/data/catalog.db` is a SQLite database with five tables: `tables` (row counts, page counts, `clustered_on` column), `columns` (distinct value counts), `indexes` (B-tree index definitions with page counts), `join_selectivity` (equi-join distinct values), and `config` (all cost model parameters). Query it with `sqlite3` or Python's `sqlite3` module to discover the full schema and statistics.

`/data/cost_model.py` provides reference cost formulas. Key physical property rules: a sequential scan's output is sorted on the table's `clustered_on` column; an index scan's output is sorted on the index column (not the clustered column); a Filter preserves its child's sort order; after any join, output is NOT sorted. Index scan is valid only when an index exists on the filtered column AND `1/distinct_values < index_selectivity_threshold` (from config). Sort-merge join is cheaper than hash join when both inputs are already sorted on their respective join columns, but requires expensive external sorts otherwise. Hash join always builds on the smaller-cardinality input.

`/data/queries.json` defines 5 queries over a star schema (fact table `orders` with dimension tables `customers`, `products`, `stores`, `dates`). `/data/main_stub.py` documents the expected output format and provides the entry point skeleton.

Running `python3 /app/main.py` must produce for each query:
- `/app/output/{query_id}_plan.json` with `query_id`, `total_cost`, and `plan` tree
- `/app/output/{query_id}_plan.dot` in graphviz DOT format
- `/app/output/{query_id}_plan.png` rendered via the `dot` command

Plan node `op` values: `SeqScan`, `IndexScan`, `Filter`, `HashJoin`, `SortMergeJoin`. Each node has `est_card` (integer), `est_cost` (this node's cost only, float), `tables` (base tables in subtree), and `children`. The critical optimization insight: scan type choice affects downstream join operator viability through sort order propagation — sometimes a more expensive scan enables a cheaper join, producing a better overall plan.