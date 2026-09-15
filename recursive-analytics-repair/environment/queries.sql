-- Transit Network Analytics Queries

-- View 1: All stations reachable from station 1 (Central) with minimum distance.
-- Returns one row per reachable station with shortest total_distance.
CREATE OR REPLACE VIEW v_reachable AS
WITH RECURSIVE reach(station_id, station_name, hops, path, total_distance) AS (
    SELECT s.id, s.name, 0::NUMERIC, ARRAY[s.id], 0.0::NUMERIC
    FROM stations s WHERE s.id = 1
    UNION ALL
    SELECT s.id, s.name, r.total_distance + c.distance, r.path || s.id, r.hops + 1
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


-- View 2: All simple (cycle-free) paths from station 1, max 4 hops.
CREATE OR REPLACE VIEW v_all_paths AS
WITH RECURSIVE paths(src, dst, path, total_dist, hops) AS (
    SELECT c.from_id, c.to_id, ARRAY[c.from_id], c.distance::NUMERIC, 1
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


-- View 3: Fibonacci-like capacity forecast (10 steps).
-- Step 1 starts at capacity=100, prev=0.
-- Each step: capacity = current + previous.
CREATE OR REPLACE VIEW v_capacity_forecast AS
WITH RECURSIVE cap(step, current_cap, prev_cap) AS (
    VALUES (1, 100, 0)
    UNION ALL
    SELECT step + 1, current_cap + current_cap, current_cap
    FROM cap
    WHERE step < 10
)
SELECT step, current_cap AS capacity FROM cap ORDER BY step;


-- View 4: Per-station ridership with cumulative passengers, moving average, and percentile.
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
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ), 2) AS moving_avg_revenue,
    RANK() OVER (
        PARTITION BY s.zone
        ORDER BY r.fare_revenue
    ) AS revenue_percentile
FROM ridership r
JOIN stations s ON s.id = r.station_id
WINDOW w AS (
    PARTITION BY r.station_id
    ORDER BY r.ride_date, r.hour
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
ORDER BY r.station_id, r.ride_date, r.hour;


-- View 5: Day-over-day percentage change in total passengers per station.
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
            PARTITION BY s.zone
            ORDER BY r.ride_date, r.station_id
        ) AS prev_day_passengers
    FROM ridership r
    JOIN stations s ON s.id = r.station_id
    GROUP BY s.zone, r.station_id, r.ride_date
) sub
ORDER BY station_id, ride_date;


-- View 6: Inter-zone passenger flow through the connection graph.
CREATE OR REPLACE VIEW v_zone_crossflow AS
SELECT
    s.zone AS origin_zone,
    CASE WHEN r.hour < 12 THEN 'morning' ELSE 'afternoon' END AS dest_zone,
    GROUPING(s.zone) AS origin_is_agg,
    GROUPING(r.hour) AS dest_is_agg,
    SUM(r.passengers) AS total_flow,
    COUNT(*) AS connection_count,
    ROUND(AVG(r.fare_revenue)::NUMERIC, 2) AS avg_flow_per_connection
FROM ridership r
JOIN stations s ON s.id = r.station_id
GROUP BY CUBE(s.zone, CASE WHEN r.hour < 12 THEN 'morning' ELSE 'afternoon' END)
ORDER BY origin_is_agg, origin_zone, dest_is_agg, dest_zone;
