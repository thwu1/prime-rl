
-- ============================================================
-- Network Analysis Pipeline
-- Computes graph analytics on the network stored in schema.sql.
-- Produces output tables: reachability, shortest_path,
--   path_detail, node_centrality, traffic_summary, network_kpis
-- ============================================================

-- ============================================================
-- Step 1: Reachability — minimum hop count between all pairs
-- ============================================================
DROP TABLE IF EXISTS reachability;
CREATE TABLE reachability(
    src_id INTEGER,
    dst_id INTEGER,
    hops INTEGER,
    PRIMARY KEY(src_id, dst_id)
);

INSERT INTO reachability
WITH RECURSIVE reach(src, dst, hops) AS (
    SELECT src, dst, 1 FROM edge
    UNION ALL
    SELECT r.src, e.dst, r.hops + 1
    FROM reach r
    JOIN edge e ON r.dst = e.src
    WHERE r.hops < 10
)
SELECT src, dst, MIN(hops) FROM reach GROUP BY src, dst;

-- ============================================================
-- Step 2: Shortest weighted paths (all-pairs)
-- ============================================================
DROP TABLE IF EXISTS shortest_path;
CREATE TABLE shortest_path(
    src_id INTEGER,
    dst_id INTEGER,
    distance REAL,
    PRIMARY KEY(src_id, dst_id)
);

INSERT INTO shortest_path
WITH RECURSIVE sp(src, dst, dist, hops) AS (
    SELECT src, dst, weight, 1 FROM edge
    UNION ALL
    SELECT sp.src, e.dst, sp.dist + e.weight, sp.hops + 1
    FROM sp
    JOIN edge e ON sp.dst = e.src
    WHERE sp.hops < 10
)
SELECT src, dst, MIN(dist) FROM sp GROUP BY src, dst;

-- ============================================================
-- Step 3: Path detail — actual shortest path routes
-- ============================================================
DROP TABLE IF EXISTS path_detail;
CREATE TABLE path_detail(
    src_id INTEGER,
    dst_id INTEGER,
    path_nodes TEXT,
    total_weight REAL,
    PRIMARY KEY(src_id, dst_id)
);

-- TODO: populate path_detail with actual shortest paths
-- Each row should contain the comma-separated node IDs of the shortest-weight
-- route and the total weight of that route.

-- ============================================================
-- Step 4: Node centrality metrics with window functions
-- ============================================================
DROP TABLE IF EXISTS node_centrality;
CREATE TABLE node_centrality(
    node_id INTEGER PRIMARY KEY,
    name TEXT,
    region TEXT,
    in_degree INTEGER,
    out_degree INTEGER,
    reach_count INTEGER,
    centrality_rank INTEGER,
    region_rank INTEGER,
    capacity_percentile REAL
);

INSERT INTO node_centrality
WITH degree_stats AS (
    SELECT
        n.id AS node_id,
        n.name,
        n.region,
        n.capacity,
        (SELECT COUNT(*) FROM edge WHERE dst = n.id) AS in_degree,
        (SELECT COUNT(*) FROM edge WHERE src = n.id) AS out_degree,
        (SELECT COUNT(*) FROM reachability WHERE src_id = n.id) AS reach_count
    FROM node n
)
SELECT
    node_id,
    name,
    region,
    in_degree,
    out_degree,
    reach_count,
    dense_rank() OVER (ORDER BY reach_count ASC) AS centrality_rank,
    rank() OVER (ORDER BY out_degree DESC) AS region_rank,
    cume_dist() OVER (ORDER BY capacity) AS capacity_percentile
FROM degree_stats;

-- ============================================================
-- Step 5: Traffic summary with advanced window functions
-- ============================================================
DROP TABLE IF EXISTS traffic_summary;
CREATE TABLE traffic_summary(
    region TEXT,
    edge_type TEXT,
    src INTEGER,
    dst INTEGER,
    weight REAL,
    region_total_weight REAL,
    region_avg_weight REAL,
    running_avg REAL,
    primary_count_so_far INTEGER
);

INSERT INTO traffic_summary
SELECT
    n.region,
    e.edge_type,
    e.src,
    e.dst,
    e.weight,
    SUM(e.weight) OVER w_region AS region_total_weight,
    AVG(e.weight) OVER w_region AS region_avg_weight,
    AVG(e.weight) OVER (
        PARTITION BY n.region
        ORDER BY e.weight
        ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
    ) AS running_avg,
    COUNT(*) OVER (
        PARTITION BY n.region
        ORDER BY e.weight
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS primary_count_so_far
FROM edge e
JOIN node n ON e.src = n.id
WINDOW w_region AS (PARTITION BY n.region);

-- ============================================================
-- Step 6: Network KPIs with UPSERT
-- ============================================================
DROP TABLE IF EXISTS network_kpis;
CREATE TABLE network_kpis(
    metric_name TEXT PRIMARY KEY,
    metric_value REAL
);

INSERT INTO network_kpis VALUES ('total_nodes', (SELECT COUNT(*) FROM node));
INSERT INTO network_kpis VALUES ('total_edges', (SELECT COUNT(*) FROM edge));
INSERT INTO network_kpis VALUES ('avg_shortest_path', 0);
INSERT INTO network_kpis VALUES ('max_hops', (SELECT MAX(hops) FROM reachability));
INSERT INTO network_kpis VALUES ('network_diameter', (SELECT MAX(distance) FROM shortest_path));

-- Update avg_shortest_path with the rounded computed value
INSERT INTO network_kpis(metric_name, metric_value)
VALUES ('avg_shortest_path', (SELECT ROUND(AVG(distance), 4) FROM shortest_path))
ON CONFLICT(metric_value) DO UPDATE SET metric_value = excluded.metric_value;

-- ============================================================
-- Step 7: Create indexes for query optimization
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_reach_src ON reachability(src_id);
CREATE INDEX IF NOT EXISTS idx_sp_src ON shortest_path(src_id);
