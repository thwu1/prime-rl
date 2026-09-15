import duckdb
import os

os.makedirs('/app', exist_ok=True)
conn = duckdb.connect('/app/insurance.duckdb')

conn.execute("""
CREATE TABLE policy (
    policy_id INTEGER PRIMARY KEY,
    policy_number VARCHAR NOT NULL,
    effective_date DATE,
    expiration_date DATE,
    status VARCHAR
)
""")

conn.execute("""
CREATE TABLE party (
    party_id INTEGER PRIMARY KEY,
    party_name VARCHAR NOT NULL,
    party_type VARCHAR
)
""")

conn.execute("""
CREATE TABLE policy_party (
    policy_id INTEGER NOT NULL,
    party_id INTEGER NOT NULL,
    role VARCHAR NOT NULL,
    PRIMARY KEY (policy_id, party_id, role),
    FOREIGN KEY (policy_id) REFERENCES policy(policy_id),
    FOREIGN KEY (party_id) REFERENCES party(party_id)
)
""")

conn.execute("""
CREATE TABLE catastrophe (
    catastrophe_id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    type VARCHAR
)
""")

conn.execute("""
CREATE TABLE claim (
    claim_id INTEGER PRIMARY KEY,
    claim_number VARCHAR NOT NULL,
    policy_id INTEGER NOT NULL,
    catastrophe_id INTEGER,
    open_date DATE,
    close_date DATE,
    status VARCHAR,
    FOREIGN KEY (policy_id) REFERENCES policy(policy_id),
    FOREIGN KEY (catastrophe_id) REFERENCES catastrophe(catastrophe_id)
)
""")

conn.execute("""
CREATE TABLE claim_amount (
    claim_amount_id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL,
    amount_type VARCHAR NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    FOREIGN KEY (claim_id) REFERENCES claim(claim_id)
)
""")

conn.execute("""
CREATE TABLE premium (
    premium_id INTEGER PRIMARY KEY,
    policy_id INTEGER NOT NULL,
    amount DECIMAL(15,2) NOT NULL,
    effective_date DATE,
    FOREIGN KEY (policy_id) REFERENCES policy(policy_id)
)
""")

conn.execute("""
INSERT INTO policy VALUES
(1, 'POL-001', '2023-01-01', '2024-01-01', 'active'),
(2, 'POL-002', '2023-03-15', '2024-03-15', 'active'),
(3, 'POL-003', '2023-06-01', '2024-06-01', 'expired'),
(4, 'POL-004', '2023-07-01', '2024-07-01', 'active'),
(5, 'POL-005', '2023-09-01', '2024-09-01', 'cancelled'),
(6, 'POL-006', '2024-01-01', '2025-01-01', 'active'),
(7, 'POL-007', '2024-02-01', '2025-02-01', 'active'),
(8, 'POL-008', '2024-04-01', '2025-04-01', 'active')
""")

conn.execute("""
INSERT INTO party VALUES
(1, 'Alice Johnson', 'individual'),
(2, 'Bob Smith', 'individual'),
(3, 'Carol Davis', 'individual'),
(4, 'Delta Insurance Agency', 'organization'),
(5, 'Epsilon Brokers', 'organization')
""")

conn.execute("""
INSERT INTO policy_party VALUES
(1, 1, 'policyholder'),
(1, 4, 'agent'),
(2, 1, 'policyholder'),
(2, 4, 'agent'),
(3, 2, 'policyholder'),
(3, 4, 'agent'),
(4, 2, 'policyholder'),
(4, 5, 'agent'),
(5, 3, 'policyholder'),
(5, 5, 'agent'),
(6, 3, 'policyholder'),
(6, 4, 'agent'),
(7, 1, 'policyholder'),
(7, 5, 'agent'),
(8, 2, 'policyholder'),
(8, 5, 'agent')
""")

conn.execute("""
INSERT INTO catastrophe VALUES
(1, 'Hurricane Alpha', 'weather'),
(2, 'Earthquake Beta', 'seismic'),
(3, 'Flood Gamma', 'weather')
""")

conn.execute("""
INSERT INTO claim VALUES
(1,  'CLM-001', 1, 1,    '2023-03-01', '2023-05-01', 'closed'),
(2,  'CLM-002', 1, NULL, '2023-04-01', '2023-06-15', 'closed'),
(3,  'CLM-003', 2, 1,    '2023-06-01', NULL,         'open'),
(4,  'CLM-004', 3, 2,    '2023-08-01', '2023-10-01', 'closed'),
(5,  'CLM-005', 3, NULL, '2023-09-01', '2023-11-01', 'closed'),
(6,  'CLM-006', 4, 3,    '2023-10-01', NULL,         'open'),
(7,  'CLM-007', 5, 1,    '2023-11-01', '2024-01-01', 'closed'),
(8,  'CLM-008', 6, NULL, '2024-03-01', '2024-05-01', 'closed'),
(9,  'CLM-009', 7, 2,    '2024-04-01', NULL,         'open'),
(10, 'CLM-010', 8, 3,    '2024-06-01', '2024-08-01', 'closed'),
(11, 'CLM-011', 1, NULL, '2023-05-15', '2023-07-20', 'closed'),
(12, 'CLM-012', 4, 1,    '2023-12-01', NULL,         'open'),
(13, 'CLM-013', 1, 1,    '2023-05-01', '2023-07-01', 'closed'),
(14, 'CLM-014', 3, 2,    '2023-09-15', NULL,         'open')
""")

conn.execute("""
INSERT INTO claim_amount VALUES
(1,  1,  'loss_payment',    5000.00),
(2,  1,  'loss_reserve',    2000.00),
(3,  1,  'expense_payment', 500.00),
(4,  1,  'expense_reserve', 300.00),
(5,  2,  'loss_payment',    3000.00),
(6,  2,  'loss_reserve',    1500.00),
(7,  3,  'loss_payment',    8000.00),
(8,  3,  'expense_payment', 1200.00),
(9,  4,  'loss_payment',    12000.00),
(10, 4,  'loss_reserve',    5000.00),
(11, 4,  'expense_payment', 2000.00),
(12, 4,  'expense_reserve', 1000.00),
(13, 5,  'loss_payment',    1500.00),
(14, 6,  'loss_payment',    25000.00),
(15, 6,  'loss_reserve',    10000.00),
(16, 6,  'expense_payment', 3000.00),
(17, 6,  'expense_reserve', 2000.00),
(18, 7,  'loss_payment',    4000.00),
(19, 7,  'loss_reserve',    1000.00),
(20, 8,  'loss_payment',    2000.00),
(21, 8,  'expense_payment', 400.00),
(22, 9,  'loss_payment',    15000.00),
(23, 9,  'loss_reserve',    8000.00),
(24, 9,  'expense_payment', 2500.00),
(25, 10, 'loss_payment',    6000.00),
(26, 10, 'loss_reserve',    3000.00),
(27, 10, 'expense_payment', 800.00),
(28, 10, 'expense_reserve', 500.00),
(29, 11, 'loss_payment',    1000.00),
(30, 12, 'loss_payment',    9000.00),
(31, 12, 'loss_reserve',    4000.00),
(32, 12, 'expense_payment', 1500.00),
(33, 12, 'expense_reserve', 750.00),
(34, 13, 'loss_payment',    3500.00),
(35, 13, 'loss_reserve',    1500.00),
(36, 14, 'loss_payment',    7500.00),
(37, 14, 'expense_payment', 1000.00)
""")

conn.execute("""
INSERT INTO premium VALUES
(1,  1, 8000.00,  '2023-01-01'),
(2,  1, 4000.00,  '2023-07-01'),
(3,  2, 8000.00,  '2023-03-15'),
(4,  3, 10000.00, '2023-06-01'),
(5,  3, 5000.00,  '2023-12-01'),
(6,  4, 10000.00, '2023-07-01'),
(7,  5, 6000.00,  '2023-09-01'),
(8,  6, 9000.00,  '2024-01-01'),
(9,  7, 11000.00, '2024-02-01'),
(10, 8, 7500.00,  '2024-04-01')
""")

conn.close()
print("Database initialized at /app/insurance.duckdb")
