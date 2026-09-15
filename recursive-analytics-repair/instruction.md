The PostgreSQL database `transit_db` contains tables `stations` (id, name, zone, elevation), `connections` (from_id, to_id, distance, travel_time, line), and `ridership` (station_id, ride_date, hour, passengers, fare_revenue). The schema and seed data are loaded from `/app/schema.sql`.

The file `/app/queries.sql` defines 6 SQL views. Each view contains one or more bugs that cause incorrect results or runtime errors. Fix all views in `/app/queries.sql` so they produce correct output.

**`v_reachable`**: Recursive CTE finding all stations reachable from station 1. Returns one row per station (via `DISTINCT ON`) with the minimum `total_distance`. Columns: `station_id`, `station_name`, `hops` (integer edge count), `total_distance` (numeric sum of connection distances along the path), `path` (integer array of visited station IDs). Station 1 itself has hops=0 and total_distance=0.

**`v_all_paths`**: All simple (cycle-free) paths originating from station 1 with at most 4 hops. Columns: `src`, `dst`, `path` (integer array containing every station visited from source through destination), `total_dist`, `hops`. No station may appear more than once in any path. Each path array must start with the source and end with the destination, and its length must equal hops+1.

**`v_capacity_forecast`**: A 10-step Fibonacci-like capacity series. Step 1 starts at capacity=100, previous=0. Each subsequent step: cap(n) = cap(n-1) + cap(n-2). Columns: `step`, `capacity`.

**`v_cumulative_stats`**: Per-station ridership records ordered by (ride_date, hour) with `cumulative_passengers` (running sum within the station), `moving_avg_revenue` (average of `fare_revenue` over a sliding window of exactly 3 records: the current and 2 preceding within the same station partition), and `revenue_percentile` (`PERCENT_RANK` of each record's `fare_revenue` within its station, ordered by fare_revenue ascending — values range from 0.0 to 1.0).

**`v_pct_change`**: Day-over-day percentage change in total passengers for each individual station. Groups ridership by (station_id, ride_date), then computes `LAG` within each station's own time series. Columns: `station_id`, `ride_date`, `total_passengers`, `prev_day_passengers`, `pct_change` (rounded to 1 decimal, NULL for first day).

**`v_zone_crossflow`**: Estimates inter-zone passenger flow through the connection graph. For each directed connection, the flow equals the total passengers at the origin station summed across all dates and hours. The view aggregates by origin zone and destination zone using `CUBE`, producing detail rows per zone pair, subtotals per origin zone, subtotals per destination zone, and a grand total. Columns: `origin_zone`, `dest_zone`, `origin_is_agg` (GROUPING flag), `dest_is_agg` (GROUPING flag), `total_flow`, `connection_count`, `avg_flow_per_connection` (rounded to 2 decimals).

Verification: `psql -U postgres -d transit_db -f /app/queries.sql` then query each view.
