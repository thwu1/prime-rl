-- Utilization cost report across datacenter and quarter dimensions

WITH quarters(quarter, qrange) AS (
    VALUES
        ('Q1 2023'::text, '[2023-01-01,2023-04-01)'::daterange),
        ('Q2 2023'::text, '[2023-04-01,2023-07-01)'::daterange),
        ('Q3 2023'::text, '[2023-07-01,2023-10-01)'::daterange),
        ('Q4 2023'::text, '[2023-10-01,2024-01-01)'::daterange)
)
SELECT datacenter,
       quarter,
       SUM((upper(a.validity) - lower(a.validity)) * a.daily_cost)::numeric AS total_cost
FROM allocations a
CROSS JOIN quarters q
WHERE a.validity && q.qrange
GROUP BY GROUPING SETS ((datacenter, quarter), (datacenter), (quarter), ())
ORDER BY datacenter NULLS LAST, quarter NULLS LAST;
