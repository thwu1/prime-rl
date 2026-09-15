CREATE TABLE transactions (
    id SERIAL PRIMARY KEY,
    account TEXT NOT NULL,
    amount NUMERIC(10,2) NOT NULL,
    fee NUMERIC(10,2) NOT NULL,
    tx_type TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    branch TEXT NOT NULL
);

INSERT INTO transactions (account, amount, fee, tx_type, created_at, branch) VALUES
('acct_001', 100.00,  2.50,  'credit', '2024-01-10 09:00:00', 'downtown'),
('acct_002', 250.00,  5.00,  'debit',  '2024-01-12 10:30:00', 'airport'),
('acct_003',  75.00,  1.50,  'credit', '2024-01-15 14:00:00', 'downtown'),
('acct_001', 500.00, 10.00,  'debit',  '2024-02-01 11:00:00', 'suburb'),
('acct_004', 150.00,  3.00,  'credit', '2024-02-10 16:00:00', 'airport'),
('acct_002', 300.00,  6.00,  'credit', '2024-02-15 09:30:00', 'downtown'),
('acct_003', 1000.00, 20.00, 'debit',  '2024-03-01 12:00:00', 'airport'),
('acct_005',  50.00,  1.00,  'credit', '2024-03-10 15:00:00', 'suburb'),
('acct_001', 200.00,  4.00,  'debit',  '2024-03-15 10:00:00', 'downtown'),
('acct_004', 425.00,  8.50,  'debit',  '2024-04-01 13:00:00', 'suburb');
