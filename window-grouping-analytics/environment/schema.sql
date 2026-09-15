-- Schema and data for hierarchical analytics task

DROP TABLE IF EXISTS transactions CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS departments CASCADE;
DROP FUNCTION IF EXISTS sorted_unique_array(TEXT[]) CASCADE;
DROP FUNCTION IF EXISTS array_intersect(TEXT[], TEXT[]) CASCADE;

-- Department hierarchy: top-level departments have NULL parent_dept_id
CREATE TABLE departments (
    dept_id SERIAL PRIMARY KEY,
    dept_name TEXT NOT NULL,
    parent_dept_id INT REFERENCES departments(dept_id)
);

INSERT INTO departments (dept_id, dept_name, parent_dept_id) VALUES
(1, 'Engineering', NULL),
(2, 'Sales', NULL),
(3, 'Marketing', NULL),
(4, 'Backend', 1),
(5, 'Frontend', 1),
(6, 'Enterprise', 2),
(7, 'SMB', 2),
(8, 'Digital', 3),
(9, 'Events', 3);

CREATE TABLE employees (
    emp_id INT PRIMARY KEY,
    emp_name TEXT NOT NULL,
    dept_id INT NOT NULL REFERENCES departments(dept_id),
    region TEXT,
    hire_date DATE NOT NULL
);

INSERT INTO employees (emp_id, emp_name, dept_id, region, hire_date) VALUES
(101, 'Alice',  4, 'North', '2022-03-15'),
(102, 'Bob',    5, 'North', '2023-01-10'),
(103, 'Carol',  6, 'South', '2021-07-01'),
(104, 'Dave',   7, 'South', '2023-06-20'),
(105, 'Eve',    8, NULL,    '2022-11-05'),
(106, 'Frank',  9, 'West',  '2021-02-28'),
(107, 'Grace',  4, 'South', '2023-09-01');

CREATE TABLE transactions (
    txn_id SERIAL PRIMARY KEY,
    emp_id INT NOT NULL REFERENCES employees(emp_id),
    product TEXT NOT NULL,
    amount NUMERIC(12,2) NOT NULL,
    txn_date DATE NOT NULL,
    tags TEXT[],
    priority INT CHECK (priority BETWEEN 1 AND 5)
);

INSERT INTO transactions (txn_id, emp_id, product, amount, txn_date, tags, priority) VALUES
( 1, 101, 'API-Server',    2500.00, '2024-01-05', '{backend,urgent}',          3),
( 2, 101, 'API-Gateway',   1800.00, '2024-01-05', '{backend,infrastructure}',  2),
( 3, 101, 'Microservice',  3200.00, '2024-01-08', '{backend}',                 4),
( 4, 101, 'Database-Opt',  2100.00, '2024-01-09', '{infrastructure,urgent}',   5),
( 5, 101, 'Cache-Layer',   1500.00, '2024-01-10', NULL,                        1),
( 6, 102, 'Dashboard',     1900.00, '2024-01-06', '{frontend,urgent}',         3),
( 7, 102, 'Mobile-App',    2800.00, '2024-01-09', '{frontend,mobile}',         4),
( 8, 103, 'CRM-License',   5200.00, '2024-01-04', '{enterprise,consulting}',   5),
( 9, 103, 'Support-Plan',  3100.00, '2024-01-05', '{enterprise,consulting}',   3),
(10, 103, 'Training',      1900.00, '2024-01-06', '{consulting}',              2),
(11, 103, 'Renewal',       4500.00, '2024-01-07', '{enterprise}',              4),
(12, 103, 'Add-Ons',       2800.00, '2024-01-08', '{enterprise,urgent}',       3),
(13, 104, 'Starter-Pack',   800.00, '2024-01-07', '{smb}',                     1),
(14, 104, 'Growth-Plan',   1200.00, '2024-01-08', '{smb,consulting}',          2),
(15, 104, 'Premium-Up',    2200.00, '2024-01-10', '{smb,premium}',             3),
(16, 105, 'Campaign-A',     950.00, '2024-01-05', '{digital,social}',          2),
(17, 105, 'Campaign-B',    1400.00, '2024-01-07', '{digital,urgent}',          3),
(18, 105, 'Campaign-C',     600.00, '2024-01-09', '{}',                        1),
(19, 106, 'Conference',    3500.00, '2024-01-04', '{events,premium}',          5),
(20, 106, 'Workshop',      1100.00, '2024-01-06', '{events}',                  2),
(21, 106, 'Sponsorship',   2700.00, '2024-01-08', '{events,premium}',          4),
(22, 107, 'API-Refactor',  2900.00, '2024-01-06', '{backend,infrastructure}',  4),
(23, 107, 'Load-Balancer', 1700.00, '2024-01-07', '{infrastructure}',          3),
(24, 107, 'Monitoring',    2300.00, '2024-01-08', '{backend,urgent}',          5),
(25, 107, 'CI-Pipeline',   1600.00, '2024-01-09', NULL,                        2);

SELECT setval('departments_dept_id_seq', 9);
SELECT setval('transactions_txn_id_seq', 25);

-- Utility function for producing sorted unique arrays
-- NOTE: This function may contain defects
CREATE OR REPLACE FUNCTION sorted_unique_array(arr TEXT[])
RETURNS TEXT[] AS $$
BEGIN
    RETURN (SELECT ARRAY_AGG(x ORDER BY x) FROM UNNEST(arr) AS x);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Utility function for computing array intersection
-- NOTE: This function may contain defects
CREATE OR REPLACE FUNCTION array_intersect(a TEXT[], b TEXT[])
RETURNS TEXT[] AS $$
BEGIN
    IF a IS NULL OR b IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN COALESCE(
        (SELECT ARRAY_AGG(x ORDER BY x)
         FROM (SELECT UNNEST(a) AS x UNION SELECT UNNEST(b) AS x) sub),
        '{}'::TEXT[]
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;
