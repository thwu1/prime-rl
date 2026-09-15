
-- ============================================================
-- Fixed Network Analysis Pipeline
-- All bugs from the original analyze.sql have been corrected.
-- path_detail table has been implemented from scratch.
-- ============================================================

-- ============================================================
-- Step 1: Reachability — minimum hop count between all pairs
-- FIX: Changed UNION ALL to UNION (prevents exponential blowup on cycles)
-- FIX: Added WHERE src != dst to exclude self-reachability
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
    UNION
    SELECT r.src, e.dst, r.hops + 1
    FROM reach r
    JOIN edge e ON r.dst = e.src
    WHERE r.hops < 10
)
SELECT src, dst, MIN(hops) FROM reach WHERE src != dst GROUP BY src, dst;

-- ============================================================
-- Step 2: Shortest weighted paths (all-pairs)
-- FIX: Added AND e.dst != sp.src to prevent cycles back to source
-- FIX: Added WHERE src != dst to exclude self-distances
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
      AND e.dst != sp.src
)
SELECT src, dst, MIN(dist) FROM sp WHERE src != dst GROUP BY src, dst;

-- ============================================================
-- Step 3: Path detail — actual shortest path routes
-- NEW: Implemented from scratch using recursive CTE with path tracking
-- ============================================================
DROP TABLE IF EXISTS path_detail;
CREATE TABLE path_detail(
    src_id INTEGER,
    dst_id INTEGER,
    path_nodes TEXT,
    total_weight REAL,
    PRIMARY KEY(src_id, dst_id)
);

INSERT INTO path_detail
WITH RECURSIVE paths(src, dst, dist, hops, path) AS (
    SELECT src, dst, weight, 1,
           CAST(src AS TEXT) || ',' || CAST(dst AS TEXT)
    FROM edge
    UNION ALL
    SELECT p.src, e.dst, p.dist + e.weight, p.hops + 1,
           p.path || ',' || CAST(e.dst AS TEXT)
    FROM paths p
    JOIN edge e ON p.dst = e.src
    WHERE p.hops < 10
      AND (',' || p.path || ',') NOT LIKE ('%,' || CAST(e.dst AS TEXT) || ',%')
)
SELECT src, dst, path, dist
FROM (
    SELECT src, dst, dist, hops, path,
           ROW_NUMBER() OVER (PARTITION BY src, dst ORDER BY dist, hops, path) AS rn
    FROM paths
    WHERE src != dst
)
WHERE rn = 1;

-- ============================================================
-- Step 4: Node centrality metrics with window functions
-- FIX: centrality_rank ORDER BY reach_count DESC (not ASC)
-- FIX: region_rank PARTITION BY region added
-- FIX: Changed cume_dist() to percent_rank()
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
    dense_rank() OVER (ORDER BY reach_count DESC) AS centrality_rank,
    rank() OVER (PARTITION BY region ORDER BY out_degree DESC) AS region_rank,
    percent_rank() OVER (ORDER BY capacity) AS capacity_percentile
FROM degree_stats;

-- ============================================================
-- Step 5: Traffic summary with advanced window functions
-- FIX: Changed ROWS to GROUPS for running_avg
-- FIX: Added FILTER (WHERE edge_type = 'primary') for primary_count_so_far
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
        GROUPS BETWEEN 1 PRECEDING AND 1 FOLLOWING
    ) AS running_avg,
    COUNT(*) FILTER (WHERE e.edge_type = 'primary') OVER (
        PARTITION BY n.region
        ORDER BY e.weight
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) AS primary_count_so_far
FROM edge e
JOIN node n ON e.src = n.id
WINDOW w_region AS (PARTITION BY n.region);

-- ============================================================
-- Step 6: Network KPIs with UPSERT
-- FIX: ON CONFLICT(metric_name) instead of ON CONFLICT(metric_value)
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

INSERT INTO network_kpis(metric_name, metric_value)
VALUES ('avg_shortest_path', (SELECT ROUND(AVG(distance), 4) FROM shortest_path))
ON CONFLICT(metric_name) DO UPDATE SET metric_value = excluded.metric_value;

-- ============================================================
-- Step 7: Create indexes for query optimization
-- FIX: Added idx_edge_dst index on edge(dst)
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_reach_src ON reachability(src_id);
CREATE INDEX IF NOT EXISTS idx_sp_src ON shortest_path(src_id);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON edge(dst);
