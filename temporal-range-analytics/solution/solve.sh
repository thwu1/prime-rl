#!/bin/bash


set -e

# SysV's wrapper can report failure in containers even after postgres has
# reached readiness (the daemon detaches before the wrapper observes it).
# Treat readiness, rather than the wrapper's exit status, as authoritative.
service postgresql start || true
for i in $(seq 1 30); do
    pg_isready -U postgres -q && break
    sleep 1
done
pg_isready -U postgres -q

# Create a fresh database
psql -U postgres -c "DROP DATABASE IF EXISTS taskdb;" 2>/dev/null || true
psql -U postgres -c "CREATE DATABASE taskdb;"
psql -U postgres -d taskdb -f /app/setup.sql

# Drop allocations table in case it was somehow created
psql -U postgres -d taskdb -c "DROP TABLE IF EXISTS allocations CASCADE;"

# Write migration.sql
cat << 'EOSQL' > /app/queries/migration.sql
CREATE TABLE allocations (
    server_id text NOT NULL,
    datacenter text NOT NULL,
    project_id int NOT NULL REFERENCES projects(id),
    validity daterange NOT NULL,
    daily_cost numeric(10,2) NOT NULL,
    EXCLUDE USING gist (server_id WITH =, validity WITH &&)
);

INSERT INTO allocations (server_id, datacenter, project_id, validity, daily_cost)
SELECT server_id, datacenter, project_id,
       daterange(
           event_date,
           COALESCE(
               lead(event_date) OVER (PARTITION BY server_id ORDER BY event_date),
               '2024-01-01'::date
           ),
           '[)'
       ),
       daily_cost
FROM raw_allocations
ORDER BY server_id, event_date;
EOSQL

# Write streaks.sql
cat << 'EOSQL' > /app/queries/streaks.sql
WITH ordered_allocs AS (
    SELECT server_id,
           daily_cost,
           lower(validity) AS alloc_date,
           LAG(daily_cost) OVER (PARTITION BY server_id ORDER BY lower(validity)) AS prev_cost
    FROM allocations
),
island_groups AS (
    SELECT server_id, daily_cost, alloc_date,
           SUM(CASE WHEN daily_cost >= prev_cost OR prev_cost IS NULL THEN 0 ELSE 1 END)
               OVER (PARTITION BY server_id ORDER BY alloc_date) AS grp
    FROM ordered_allocs
),
streak_stats AS (
    SELECT server_id, grp,
           COUNT(*)     AS streak_length,
           MIN(alloc_date) AS streak_start,
           MAX(alloc_date) AS streak_end
    FROM island_groups
    GROUP BY server_id, grp
),
best_per_server AS (
    SELECT DISTINCT ON (server_id)
           server_id, streak_length, streak_start, streak_end
    FROM streak_stats
    ORDER BY server_id, streak_length DESC, streak_start ASC
)
SELECT server_id, streak_length, streak_start, streak_end
FROM best_per_server
ORDER BY streak_length DESC, server_id ASC
LIMIT 5;
EOSQL

# Write project_rollup.sql
cat << 'EOSQL' > /app/queries/project_rollup.sql
WITH RECURSIVE
project_days AS (
    SELECT p.id, p.name, p.parent_id,
           COALESCE(SUM(upper(a.validity) - lower(a.validity)), 0)::int AS own_days
    FROM projects p
    LEFT JOIN allocations a ON a.project_id = p.id
    GROUP BY p.id, p.name, p.parent_id
),
tree AS (
    SELECT id, name, parent_id, 0 AS depth, name::text AS path
    FROM project_days
    WHERE parent_id IS NULL

    UNION ALL

    SELECT pd.id, pd.name, pd.parent_id, t.depth + 1,
           t.path || ' > ' || pd.name
    FROM project_days pd
    JOIN tree t ON pd.parent_id = t.id
),
descendants(root_id, desc_id) AS (
    SELECT id, id FROM projects

    UNION ALL

    SELECT d.root_id, p.id
    FROM descendants d
    JOIN projects p ON p.parent_id = d.desc_id
),
totals AS (
    SELECT d.root_id AS project_id,
           COALESCE(SUM(pd.own_days), 0)::int AS total_server_days
    FROM descendants d
    LEFT JOIN project_days pd ON pd.id = d.desc_id
    GROUP BY d.root_id
)
SELECT t.name       AS project_name,
       t.depth,
       t.path,
       COALESCE(pd.own_days, 0) AS own_server_days,
       tot.total_server_days
FROM tree t
LEFT JOIN project_days pd ON pd.id = t.id
JOIN totals tot ON tot.project_id = t.id
ORDER BY t.path;
EOSQL

# Write utilization_report.sql
cat << 'EOSQL' > /app/queries/utilization_report.sql
WITH quarters(quarter, qrange) AS (
    VALUES
        ('Q1 2023'::text, '[2023-01-01,2023-04-01)'::daterange),
        ('Q2 2023'::text, '[2023-04-01,2023-07-01)'::daterange),
        ('Q3 2023'::text, '[2023-07-01,2023-10-01)'::daterange),
        ('Q4 2023'::text, '[2023-10-01,2024-01-01)'::daterange)
),
costs AS (
    SELECT a.datacenter,
           q.quarter,
           (upper(a.validity * q.qrange) - lower(a.validity * q.qrange))
               * a.daily_cost AS cost
    FROM allocations a
    CROSS JOIN quarters q
    WHERE a.validity && q.qrange
)
SELECT datacenter,
       quarter,
       SUM(cost)::numeric AS total_cost
FROM costs
GROUP BY GROUPING SETS ((datacenter, quarter), (datacenter), (quarter), ())
ORDER BY datacenter NULLS LAST, quarter NULLS LAST;
EOSQL

# Run migration
psql -U postgres -d taskdb -f /app/queries/migration.sql

# Verify all queries execute successfully
echo "=== Streaks ==="
psql -U postgres -d taskdb -f /app/queries/streaks.sql
echo "=== Project Rollup ==="
psql -U postgres -d taskdb -f /app/queries/project_rollup.sql
echo "=== Utilization Report ==="
psql -U postgres -d taskdb -f /app/queries/utilization_report.sql

echo "All queries executed successfully."
