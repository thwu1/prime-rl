-- Analytical queries for HTTP-range-request optimization.
-- Each query must be optimized so SQLite reads only from indexes,
-- never performing unnecessary table lookups.
--

-- Q1: Unique visitors by country in a time window
SELECT country, COUNT(DISTINCT user_id) AS unique_visitors
FROM events
WHERE event_type = 'pageview'
  AND timestamp BETWEEN 1696200000 AND 1696500000
GROUP BY country
ORDER BY unique_visitors DESC;

-- Q2: Top pages by distinct mobile sessions
SELECT page_url, COUNT(DISTINCT session_id) AS sessions
FROM events
WHERE device_type = 'mobile'
  AND event_type = 'pageview'
GROUP BY page_url
ORDER BY sessions DESC
LIMIT 20;

-- Q3: Revenue aggregation by user plan type (join)
SELECT u.plan_type,
       SUM(e.revenue_cents) AS total_revenue,
       COUNT(*) AS num_purchases
FROM events e
JOIN users u ON e.user_id = u.id
WHERE e.event_type = 'purchase'
GROUP BY u.plan_type
ORDER BY total_revenue DESC;

-- Q4: Session bounce rate by device type (subquery)
SELECT device_type,
       COUNT(*) AS total_sessions,
       SUM(CASE WHEN pv_count = 1 THEN 1 ELSE 0 END) AS bounced_sessions,
       ROUND(100.0 * SUM(CASE WHEN pv_count = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS bounce_rate
FROM (
    SELECT session_id, device_type, COUNT(*) AS pv_count
    FROM events
    WHERE event_type = 'pageview'
    GROUP BY session_id
)
GROUP BY device_type;

-- Q5: Referrer conversion — sessions with vs. without purchases (self-join)
SELECT e1.referrer,
       COUNT(DISTINCT e1.session_id) AS total_sessions,
       COUNT(DISTINCT e2.session_id) AS purchase_sessions
FROM events e1
LEFT JOIN events e2
  ON e1.session_id = e2.session_id
  AND e2.event_type = 'purchase'
WHERE e1.event_type = 'pageview'
  AND e1.referrer IS NOT NULL
GROUP BY e1.referrer
ORDER BY purchase_sessions DESC;

-- Q6: Engagement metrics by page category (two-table join)
SELECT p.category,
       COUNT(*) AS pageviews,
       AVG(e.duration_ms) AS avg_duration_ms,
       COUNT(DISTINCT e.user_id) AS unique_users
FROM events e
JOIN pages p ON e.page_url = p.url
WHERE e.event_type = 'pageview'
  AND e.duration_ms IS NOT NULL
GROUP BY p.category
ORDER BY avg_duration_ms DESC;

-- Q7: High-value purchase analysis by country
SELECT country,
       COUNT(*) AS num_purchases,
       SUM(revenue_cents) AS total_revenue,
       AVG(revenue_cents) AS avg_revenue,
       MAX(revenue_cents) AS max_revenue
FROM events
WHERE event_type = 'purchase'
  AND revenue_cents > 10000
GROUP BY country
HAVING COUNT(*) >= 3
ORDER BY total_revenue DESC;

-- Q8: Daily pageview trends over first week
SELECT date(timestamp, 'unixepoch') AS day,
       COUNT(*) AS pageviews,
       COUNT(DISTINCT user_id) AS unique_users
FROM events
WHERE event_type = 'pageview'
  AND timestamp >= 1696118400
  AND timestamp < 1696723200
GROUP BY date(timestamp, 'unixepoch')
ORDER BY day;
