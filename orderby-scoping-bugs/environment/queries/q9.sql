-- Report: transactions sorted by total cost (amount + fee)
SELECT account, amount, fee,
       amount + fee AS total_cost
FROM transactions
ORDER BY amount + fee;
