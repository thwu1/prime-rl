#!/usr/bin/env bash

# Reference solution: fix all 6 buggy SQL views in /app/queries.sql

cat > /app/queries.sql << 'SQLEOF'
-- Transit Network Analytics Queries (Fixed)

-- View 1 FIX: correct column ordering in recursive term
-- Bug was: positions 3 and 5 were swapped (hops got distance, distance got hops)
CREATE OR REPLACE VIEW v_reachable AS
WITH RECURSIVE reach(station_id, station_name, hops, path, total_distance) AS (
    SELECT s.id, s.name, 0::NUMERIC, ARRAY[s.id], 0.0::NUMERIC
    FROM stations s WHERE s.id = 1
    UNION ALL
    SELECT s.id, s.name, r.hops + 1, r.path || s.id, r.total_distance + c.distance
    FROM reach r
    JOIN connections c ON c.from_id = r.station_id
    JOIN stations s ON s.id = c.to_id
    WHERE NOT (s.id = ANY(r.path))
      AND r.hops < 5
)
SELECT DISTINCT ON (station_id)
    station_id, station_name, hops, total_distance, path
FROM reach
ORDER BY station_id, total_distance;


-- View 2 FIX: anchor path must include both from_id and to_id
-- Bug was: ARRAY[c.from_id] missed the first destination, breaking cycle detection
CREATE OR REPLACE VIEW v_all_paths AS
WITH RECURSIVE paths(src, dst, path, total_dist, hops) AS (
    SELECT c.from_id, c.to_id, ARRAY[c.from_id, c.to_id], c.distance::NUMERIC, 1
    FROM connections c
    WHERE c.from_id = 1
    UNION ALL
    SELECT p.src, c.to_id, p.path || c.to_id, p.total_dist + c.distance, p.hops + 1
    FROM paths p
    JOIN connections c ON c.from_id = p.dst
    WHERE NOT (c.to_id = ANY(p.path))
      AND p.hops < 4
)
SELECT src, dst, path, total_dist, hops
FROM paths
ORDER BY src, dst, total_dist;


-- View 3 FIX: Fibonacci formula current_cap + prev_cap
-- Bug was: current_cap + current_cap (doubling instead of Fibonacci)
CREATE OR REPLACE VIEW v_capacity_forecast AS
WITH RECURSIVE cap(step, current_cap, prev_cap) AS (
    VALUES (1, 100, 0)
    UNION ALL
    SELECT step + 1, current_cap + prev_cap, current_cap
    FROM cap
    WHERE step < 10
)
SELECT step, current_cap AS capacity FROM cap ORDER BY step;


-- View 4 FIX: 3-row moving average + PERCENT_RANK partitioned by station_id
-- Bug was: UNBOUNDED PRECEDING (running avg), RANK() instead of PERCENT_RANK(),
-- and partitioned by zone instead of station_id
CREATE OR REPLACE VIEW v_cumulative_stats AS
SELECT
    r.station_id,
    r.ride_date,
    r.hour,
    r.passengers,
    r.fare_revenue,
    SUM(r.passengers) OVER w AS cumulative_passengers,
    ROUND(AVG(r.fare_revenue) OVER (
        PARTITION BY r.station_id
        ORDER BY r.ride_date, r.hour
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ), 2) AS moving_avg_revenue,
    PERCENT_RANK() OVER (
        PARTITION BY r.station_id
        ORDER BY r.fare_revenue
    ) AS revenue_percentile
FROM ridership r
WINDOW w AS (
    PARTITION BY r.station_id
    ORDER BY r.ride_date, r.hour
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
ORDER BY r.station_id, r.ride_date, r.hour;


-- View 5 FIX: LAG partitioned by station_id, remove unnecessary zone grouping
-- Bug was: LAG partitioned by zone (cross-station contamination)
CREATE OR REPLACE VIEW v_pct_change AS
SELECT
    station_id,
    ride_date,
    total_passengers,
    prev_day_passengers,
    CASE
        WHEN prev_day_passengers IS NOT NULL AND prev_day_passengers > 0
        THEN ROUND((total_passengers - prev_day_passengers)::NUMERIC
                    / prev_day_passengers * 100, 1)
        ELSE NULL
    END AS pct_change
FROM (
    SELECT
        r.station_id,
        r.ride_date,
        SUM(r.passengers) AS total_passengers,
        LAG(SUM(r.passengers)) OVER (
            PARTITION BY r.station_id
            ORDER BY r.ride_date
        ) AS prev_day_passengers
    FROM ridership r
    GROUP BY r.station_id, r.ride_date
) sub
ORDER BY station_id, ride_date;


-- View 6 FIX: Complete redesign for inter-zone flow through connections
-- Bug was: entirely wrong structure — grouped ridership by zone/time_period instead
-- of deriving zone-pair flows through the connections graph
CREATE OR REPLACE VIEW v_zone_crossflow AS
WITH connection_flow AS (
    SELECT
        s_from.zone AS origin_zone,
        s_to.zone AS dest_zone,
        SUM(r.passengers) AS flow
    FROM connections c
    JOIN stations s_from ON s_from.id = c.from_id
    JOIN stations s_to ON s_to.id = c.to_id
    JOIN ridership r ON r.station_id = c.from_id
    GROUP BY s_from.zone, s_to.zone, c.from_id, c.to_id
)
SELECT
    origin_zone,
    dest_zone,
    GROUPING(origin_zone) AS origin_is_agg,
    GROUPING(dest_zone) AS dest_is_agg,
    SUM(flow) AS total_flow,
    COUNT(*) AS connection_count,
    ROUND(AVG(flow)::NUMERIC, 2) AS avg_flow_per_connection
FROM connection_flow
GROUP BY CUBE(origin_zone, dest_zone)
ORDER BY origin_is_agg, origin_zone, dest_is_agg, dest_zone;
SQLEOF
