A colleague analyzed implication relationships between 12 equational laws of magmas (sets with a single binary operation) over all finite models of orders 1, 2, and 3. Their working files are in `/app/analysis/`:

- `equations.p` — the 12 laws in Prover9-style notation (`f(x,y)` denotes the binary operation)
- `claimed_implications.csv` — a 12x12 matrix where entry (i,j)=1 claims that every magma of order ≤3 satisfying law E_i also satisfies E_j
- `notes.txt` — the colleague's analysis notes describing their methodology and assumptions

The claimed implication matrix contains errors — both false implications and missed true implications. The colleague's notes reveal their reasoning but do not identify which specific entries are wrong.

Audit the claimed matrix: identify and correct every error, produce counterexample magmas for each non-implication, and generate a Hasse diagram of the corrected implication partial order.

A **magma of order n** has elements {0, 1, ..., n-1} and an operation table stored as a flat row-major array of n*n entries, where index a*n + b gives the result of a * b. Total magmas: order 1 has 1, order 2 has 16, order 3 has 19683.

Write results to `/app/results/`:

- `corrected_matrix.csv` — corrected 12x12 CSV (no header, no index). Entry at row i, column j is 1 if E_i implies E_j over all magmas of order ≤ 3, else 0. Diagonal entries are 1.
- `counterexamples.json` — JSON object. For each ordered pair (i,j) where E_i does NOT imply E_j, include key `"i,j"` mapping to `{"order": n, "table": [<flat row-major n*n array>]}` — a magma of order ≤ 3 satisfying E_i but not E_j.
- `error_report.json` — JSON list of objects `{"row": i, "col": j, "claimed": v, "correct": c}` for every cell where the claimed matrix disagrees with the corrected matrix (1-indexed equation IDs).
- `hasse.dot` — Graphviz DOT source for the Hasse diagram (transitive reduction) of the corrected implication partial order, with nodes labeled E1 through E12 and directed edges E_i -> E_j for each covering relation.
- `hasse.png` — rendered Hasse diagram image produced from the DOT source.