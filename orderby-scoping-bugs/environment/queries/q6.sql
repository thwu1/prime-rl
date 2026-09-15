-- Report: transactions sorted by account (C locale) then by amount
SELECT account AS acct, amount
FROM transactions
ORDER BY account COLLATE "C", amount;
