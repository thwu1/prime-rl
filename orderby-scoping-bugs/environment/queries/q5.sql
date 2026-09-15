-- Report: accounts ranked by total, showing rank position
SELECT account,
       SUM(amount) AS total,
       RANK() OVER (ORDER BY total DESC) AS ranking
FROM transactions
GROUP BY account
ORDER BY ranking;
