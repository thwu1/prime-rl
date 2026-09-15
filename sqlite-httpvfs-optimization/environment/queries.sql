
-- Q1: Count purchase events per country in January 2024
SELECT country_code, COUNT(*) as cnt
FROM events
WHERE event_type = 'purchase'
  AND ts >= 1704067200 AND ts < 1706745600
GROUP BY country_code
ORDER BY cnt DESC;

-- Q2: Top 20 users by total value in the 'electronics' category
SELECT user_id, SUM(value) as total_value
FROM events
WHERE category = 'electronics' AND value IS NOT NULL
GROUP BY user_id
ORDER BY total_value DESC
LIMIT 20;

-- Q3: 10 most recent events for a specific user
SELECT ts, event_type
FROM events
WHERE user_id = 'U00042'
ORDER BY ts DESC
LIMIT 10;

-- Q4: Unique user count per device type for pageview events
SELECT device, COUNT(DISTINCT user_id) as unique_users
FROM events
WHERE event_type = 'pageview'
GROUP BY device;

-- Q5: Average purchase value and count by category
SELECT category, AVG(value) as avg_value, COUNT(*) as cnt
FROM events
WHERE event_type = 'purchase' AND value > 0
GROUP BY category
ORDER BY avg_value DESC;

-- Q6: US purchase revenue and buyer stats for July 2024
SELECT SUM(value) as total_revenue,
       COUNT(*) as num_transactions,
       COUNT(DISTINCT user_id) as unique_buyers
FROM events
WHERE event_type = 'purchase'
  AND country_code = 'US'
  AND ts >= 1719792000 AND ts < 1722470400;

-- Q7: Purchase history for a specific user
SELECT event_type, ts, value
FROM events
WHERE user_id = 'U00042' AND event_type = 'purchase'
ORDER BY ts DESC;
