-- Query 3: Volume-Weighted Average Price per Instrument (March 2024)
-- =====================================================================
-- Calculate the VWAP for each instrument using daily closing prices
-- and volumes for March 2024.
-- VWAP = SUM(close_price * volume) / SUM(volume)
--
-- Expected output columns: symbol, vwap
-- Ordered by: symbol ASC
-- VWAP should be rounded to 4 decimal places.

SELECT
    i.symbol,
    ROUND(AVG(dp.close_price), 4) AS vwap
FROM daily_prices dp
JOIN instruments i ON dp.instrument_id = i.id
WHERE dp.price_date >= '2024-03-01'
  AND dp.price_date <= '2024-03-31'
GROUP BY i.symbol
ORDER BY i.symbol;
