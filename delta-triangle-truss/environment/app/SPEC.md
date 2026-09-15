# Output Specification

## Data Source

The pipeline processes a dynamic undirected graph. Edge data files are in `/data/`.

## Build and Run

The pipeline is orchestrated by the Makefile in `/app/`. Running `make all` should
build the Rust graph engine, execute it to produce triangle analytics, and then
run the Python truss decomposition on the final graph state.

## Output 1: Triangle Counts

File: `/app/output/triangle_counts.txt`

After processing each batch of edge operations, record the total number of triangles
in the current graph state. A triangle is an unordered set of three distinct nodes
{a, b, c} where all three edges (a,b), (a,c), and (b,c) exist simultaneously.

Format: exactly 300 lines. Each line: `<batch_id> <total_triangle_count>`.
Batch IDs from 0 through 299 in ascending order.

## Output 2: Per-Node Triangle Participation

File: `/app/output/node_triangles.txt`

For the final graph state (after all batches have been applied), report the number of
distinct triangles containing each node. Only include nodes whose count is positive.

Format: one line per participating node, `<node_id> <count>`, sorted ascending by
node_id.

**Consistency property**: the sum of all per-node counts must equal exactly
3 times the total triangle count in the final graph, since each triangle
contributes to the count of each of its three vertices.

## Output 3: Truss Decomposition

File: `/app/output/truss_decomposition.txt`

For the final graph state, compute the truss number of every edge. The truss number of
an edge is the maximum k such that the edge belongs to a k-truss subgraph. A k-truss
is a maximal subgraph in which every edge participates in at least (k-2) triangles
within that subgraph. Every edge in a non-empty graph has truss number at least 2.

Format: one line per edge, `<u> <v> <truss_number>` where u < v, sorted ascending
by (u, v).
