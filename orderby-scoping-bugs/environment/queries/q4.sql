-- Report: transactions with inverted amounts, sorted by the inverted amount ascending
SELECT account, -amount AS "Amount"
FROM transactions
ORDER BY amount;
