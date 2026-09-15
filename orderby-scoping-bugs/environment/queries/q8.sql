-- Report: transactions sorted by account alias (C locale) then amount
SELECT account AS acct, amount
FROM transactions
ORDER BY acct COLLATE "C", amount;
