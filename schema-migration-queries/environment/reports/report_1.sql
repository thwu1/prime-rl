-- Pricing Summary Report
-- Aggregates line-item pricing data by return flag and line status
-- for items shipped on or before 1998-09-02
SELECT
    f.return_flag,
    f.line_status,
    SUM(f.quantity) AS total_qty,
    SUM(f.extended_price) AS total_base_price,
    SUM(f.extended_price * (1 - f.discount)) AS total_disc_price,
    SUM(f.extended_price * (1 - f.discount) * (1 + f.tax)) AS total_charge,
    AVG(f.quantity) AS avg_qty,
    AVG(f.extended_price) AS avg_price,
    AVG(f.discount) AS avg_disc,
    COUNT(*) AS count_lines
FROM fact_sales f
WHERE f.ship_date <= DATE '1998-09-02'
GROUP BY f.return_flag, f.line_status
ORDER BY f.return_flag, f.line_status;
