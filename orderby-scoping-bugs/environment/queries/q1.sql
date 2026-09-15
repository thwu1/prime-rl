-- Report: transactions sorted by amount ascending (smallest first)
SELECT account, -amount AS amount
FROM transactions
ORDER BY amount;
