
-- Club Analytics Pipeline — Corrected

DROP FUNCTION IF EXISTS cd.member_value_score(INT) CASCADE;
DROP VIEW IF EXISTS cd.booking_anomaly_report CASCADE;
DROP VIEW IF EXISTS cd.revenue_rolling_stats CASCADE;
DROP VIEW IF EXISTS cd.daily_facility_revenue CASCADE;
DROP VIEW IF EXISTS cd.member_network_stats CASCADE;
DROP VIEW IF EXISTS cd.facility_monthly_analysis CASCADE;

-- ============================================================
-- View 1: cd.daily_facility_revenue (FIXED)
-- Uses GENERATE_SERIES cross-joined with facilities and LEFT JOIN
-- to bookings so zero-revenue days appear.
-- ============================================================
CREATE OR REPLACE VIEW cd.daily_facility_revenue AS
WITH date_series AS (
    SELECT generate_series('2012-07-01'::date, '2013-01-31'::date, '1 day'::interval)::date AS date
),
all_combos AS (
    SELECT f.facid, f.name AS facility_name, d.date
    FROM cd.facilities f
    CROSS JOIN date_series d
),
daily_rev AS (
    SELECT
        b.facid,
        CAST(b.starttime AS date) AS date,
        SUM(CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                 ELSE b.slots * f.membercost END) AS revenue
    FROM cd.bookings b
    JOIN cd.facilities f ON f.facid = b.facid
    GROUP BY b.facid, CAST(b.starttime AS date)
)
SELECT
    ac.facility_name,
    ac.facid,
    ac.date,
    COALESCE(dr.revenue, 0) AS revenue
FROM all_combos ac
LEFT JOIN daily_rev dr ON dr.facid = ac.facid AND dr.date = ac.date
ORDER BY ac.facility_name, ac.date;


-- ============================================================
-- View 2: cd.revenue_rolling_stats (FIXED)
-- Window computed over full date range (including July for lookback),
-- then filtered to Aug-Sep. Uses 14 PRECEDING and STDDEV_POP.
-- ============================================================
CREATE OR REPLACE VIEW cd.revenue_rolling_stats AS
WITH base AS (
    SELECT
        facility_name, facid, date, revenue,
        AVG(revenue) OVER (
            PARTITION BY facid ORDER BY date
            ROWS BETWEEN 14 PRECEDING AND CURRENT ROW
        ) AS rolling_avg,
        STDDEV_POP(revenue) OVER (
            PARTITION BY facid ORDER BY date
            ROWS BETWEEN 14 PRECEDING AND CURRENT ROW
        ) AS rolling_stddev
    FROM cd.daily_facility_revenue
)
SELECT
    facility_name, facid, date, revenue, rolling_avg, rolling_stddev,
    CASE WHEN rolling_stddev = 0 OR rolling_stddev IS NULL THEN NULL
         ELSE (revenue - rolling_avg) / rolling_stddev END AS zscore
FROM base
WHERE date >= '2012-08-01' AND date < '2012-10-01'
ORDER BY facility_name, date;


-- ============================================================
-- View 3: cd.member_network_stats (FIXED)
-- Recursive CTE traverses DOWNWARD (m.recommendedby = n.current_member).
-- Direct referrals counted separately. Network revenue computed
-- from descendant bookings.
-- ============================================================
CREATE OR REPLACE VIEW cd.member_network_stats AS
WITH RECURSIVE network AS (
    SELECT memid AS root_member, memid AS current_member, 0 AS depth
    FROM cd.members

    UNION ALL

    SELECT n.root_member, m.memid, n.depth + 1
    FROM network n
    JOIN cd.members m ON m.recommendedby = n.current_member
),
descendants AS (
    SELECT root_member, current_member, depth
    FROM network
    WHERE depth > 0
),
net_rev AS (
    SELECT
        d.root_member,
        COALESCE(SUM(
            CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                 ELSE b.slots * f.membercost END
        ), 0) AS revenue
    FROM descendants d
    LEFT JOIN cd.bookings b ON b.memid = d.current_member
    LEFT JOIN cd.facilities f ON f.facid = b.facid
    GROUP BY d.root_member
)
SELECT
    m.memid,
    m.firstname,
    m.surname,
    COALESCE((SELECT COUNT(*) FROM cd.members x WHERE x.recommendedby = m.memid), 0)::int AS direct_referrals,
    COALESCE((SELECT COUNT(DISTINCT current_member) FROM descendants WHERE root_member = m.memid), 0)::int AS total_network_size,
    COALESCE((SELECT MAX(depth) FROM descendants WHERE root_member = m.memid), 0)::int AS max_depth,
    COALESCE(nr.revenue, 0) AS network_revenue
FROM cd.members m
LEFT JOIN net_rev nr ON nr.root_member = m.memid
ORDER BY m.memid;


-- ============================================================
-- View 4: cd.facility_monthly_analysis (FIXED)
-- Uses actual days-in-month via date arithmetic, LAG for
-- prev_month_revenue, and NTILE(3) for category.
-- ============================================================
CREATE OR REPLACE VIEW cd.facility_monthly_analysis AS
WITH monthly AS (
    SELECT
        f.name AS facility_name,
        f.facid,
        DATE_TRUNC('month', b.starttime) AS month,
        SUM(CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                 ELSE b.slots * f.membercost END) AS total_revenue,
        SUM(b.slots) AS total_slots
    FROM cd.facilities f
    INNER JOIN cd.bookings b ON f.facid = b.facid
    GROUP BY f.name, f.facid, DATE_TRUNC('month', b.starttime)
),
with_util AS (
    SELECT
        facility_name, facid, month, total_revenue, total_slots,
        ROUND(100.0 * total_slots / (25 * ((month + INTERVAL '1 month')::date - month::date)), 1) AS utilization_pct
    FROM monthly
),
with_window AS (
    SELECT
        facility_name, facid, month, total_revenue, utilization_pct,
        LAG(total_revenue) OVER (PARTITION BY facid ORDER BY month) AS prev_month_revenue,
        RANK() OVER (PARTITION BY month ORDER BY total_revenue DESC) AS revenue_rank,
        NTILE(3) OVER (PARTITION BY month ORDER BY total_revenue DESC) AS tile
    FROM with_util
)
SELECT
    facility_name, month, total_revenue, utilization_pct, revenue_rank,
    prev_month_revenue,
    CASE WHEN prev_month_revenue IS NOT NULL AND prev_month_revenue > 0
         THEN ROUND(((total_revenue - prev_month_revenue) / prev_month_revenue) * 100, 1)
         ELSE NULL END AS growth_pct,
    CASE tile WHEN 1 THEN 'high' WHEN 2 THEN 'medium' WHEN 3 THEN 'low' END AS category
FROM with_window
ORDER BY facility_name, month;


-- ============================================================
-- View 5: cd.booking_anomaly_report (IMPLEMENTED)
-- Joins revenue_rolling_stats with booking details to find
-- anomalous days and dominant bookers.
-- ============================================================
CREATE OR REPLACE VIEW cd.booking_anomaly_report AS
WITH anomalous_days AS (
    SELECT facility_name, facid, date, revenue, zscore,
           CASE WHEN zscore > 0 THEN 'spike' ELSE 'dip' END AS anomaly_type
    FROM cd.revenue_rolling_stats
    WHERE ABS(zscore) > 1.5
),
booking_revenue AS (
    SELECT
        b.facid,
        CAST(b.starttime AS date) AS bdate,
        b.memid,
        SUM(CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
                 ELSE b.slots * f.membercost END) AS member_revenue
    FROM cd.bookings b
    JOIN cd.facilities f ON f.facid = b.facid
    WHERE CAST(b.starttime AS date) >= '2012-08-01'
      AND CAST(b.starttime AS date) < '2012-10-01'
    GROUP BY b.facid, CAST(b.starttime AS date), b.memid
),
ranked AS (
    SELECT
        br.facid, br.bdate, br.memid, br.member_revenue,
        ROW_NUMBER() OVER (
            PARTITION BY br.facid, br.bdate
            ORDER BY br.member_revenue DESC, br.memid
        ) AS rn
    FROM booking_revenue br
    INNER JOIN anomalous_days ad ON ad.facid = br.facid AND ad.date = br.bdate
)
SELECT
    ad.facility_name,
    ad.facid,
    ad.date,
    ad.revenue,
    ad.zscore,
    ad.anomaly_type,
    CASE WHEN r.memid = 0 THEN 'GUEST'
         ELSE m.firstname || ' ' || m.surname END AS dominant_booker,
    CASE WHEN ad.revenue = 0 THEN NULL
         ELSE ROUND(100.0 * r.member_revenue / ad.revenue, 1) END AS dominant_pct
FROM anomalous_days ad
LEFT JOIN ranked r ON r.facid = ad.facid AND r.bdate = ad.date AND r.rn = 1
LEFT JOIN cd.members m ON m.memid = r.memid
ORDER BY ad.facid, ad.date;


-- ============================================================
-- Function: cd.member_value_score (FIXED)
-- Uses membercost/guestcost correctly, fixed date for tenure,
-- 0.5 weight on network_revenue, GREATEST to prevent div-by-zero.
-- ============================================================
CREATE OR REPLACE FUNCTION cd.member_value_score(p_memid INT)
RETURNS NUMERIC AS $$
DECLARE
    v_direct_revenue NUMERIC;
    v_network_revenue NUMERIC;
    v_tenure_months INT;
BEGIN
    SELECT COALESCE(SUM(
        CASE WHEN b.memid = 0 THEN b.slots * f.guestcost
             ELSE b.slots * f.membercost END
    ), 0)
    INTO v_direct_revenue
    FROM cd.bookings b
    JOIN cd.facilities f ON f.facid = b.facid
    WHERE b.memid = p_memid;

    SELECT COALESCE(network_revenue, 0)
    INTO v_network_revenue
    FROM cd.member_network_stats
    WHERE memid = p_memid;

    SELECT EXTRACT(YEAR FROM AGE('2013-02-01'::date, joindate)) * 12 +
           EXTRACT(MONTH FROM AGE('2013-02-01'::date, joindate))
    INTO v_tenure_months
    FROM cd.members
    WHERE memid = p_memid;

    RETURN ROUND((v_direct_revenue + 0.5 * v_network_revenue) / GREATEST(v_tenure_months, 1), 2);
END;
$$ LANGUAGE plpgsql;
