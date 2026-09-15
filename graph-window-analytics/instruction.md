The file `/app/analyze.sql` implements a data pipeline for analyzing a directed weighted network graph. The schema and seed data are in `/app/schema.sql`; running `/app/run.sh` creates the database, loads the schema, and executes the analysis. The pipeline currently fails or produces incorrect results. Fix and complete `/app/analyze.sql` so that `/app/run.sh` exits 0 and the database `/app/network.db` contains all required output tables with correct data.

The network contains 10 nodes across three regions (alpha, beta, gamma) with 18 directed weighted edges. Gamma is a sink region with no outbound edges to other regions.

**Required output tables:**

`reachability(src_id, dst_id, hops)` — Minimum hop count between all reachable pairs of distinct nodes. Self-pairs must not appear. Must terminate correctly on cyclic subgraphs without unbounded growth.

`shortest_path(src_id, dst_id, distance)` — Minimum weighted distance between all reachable pairs of distinct nodes. Self-pairs must not appear. Must handle cycles without infinite recursion.

`path_detail(src_id, dst_id, path_nodes, total_weight)` — For every pair in `shortest_path`, the actual minimum-weight route as a comma-separated string of node IDs from source to destination (e.g., `'1,3,4,6'`). `total_weight` must match the corresponding `shortest_path.distance`. When multiple paths share the minimum weight, prefer fewer hops. Paths must not revisit any node.

`node_centrality(node_id, name, region, in_degree, out_degree, reach_count, centrality_rank, region_rank, capacity_percentile)` — One row per node. `reach_count`: count of distinct other nodes reachable from this node. `centrality_rank`: global rank by connectivity with most-connected nodes at rank 1; nodes with equal connectivity share the same rank and no ranks are skipped. `region_rank`: rank within the node's own region by outgoing edge count (highest first); tied nodes share a rank and subsequent ranks are skipped. `capacity_percentile`: relative position in the capacity distribution across all nodes, where the lowest-capacity node scores 0.0 and the highest scores 1.0.

`traffic_summary(region, edge_type, src, dst, weight, region_total_weight, region_avg_weight, running_avg, primary_count_so_far)` — One row per edge, joined to its source node's region. `region_total_weight` and `region_avg_weight` span the full region partition. `running_avg`: moving average of weight within each region ordered by weight, computed over a symmetric window of one adjacent weight-level on each side; all rows sharing the same weight value form a single unit in the window frame. `primary_count_so_far`: cumulative count from start of the region through the current row (ordered by weight), counting only edges where `edge_type = 'primary'`.

`network_kpis(metric_name, metric_value)` — Rows for: `total_nodes`, `total_edges`, `avg_shortest_path` (rounded to 4 decimal places), `max_hops`, `network_diameter`. All values must be correctly computed from the other output tables.

An index on `edge(dst)` must exist after the pipeline completes.

Success: `/app/run.sh` exits 0 and all output tables contain correct data.
