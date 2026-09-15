-- Report: all credit and debit transactions, sorted by amount descending
(SELECT account, amount, 'credit' AS direction FROM transactions WHERE tx_type = 'credit')
UNION ALL
(SELECT account, amount, 'debit' AS direction FROM transactions WHERE tx_type = 'debit')
ORDER BY -amount;
