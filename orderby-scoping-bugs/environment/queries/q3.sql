-- Report: accounts ranked by total transaction amount
SELECT account,
       SUM(amount) AS total,
       RANK() OVER (ORDER BY SUM(amount) DESC) AS ranking
FROM transactions
GROUP BY account
ORDER BY ranking;
