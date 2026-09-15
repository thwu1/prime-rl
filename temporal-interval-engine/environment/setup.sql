-- Temporal Interval Reconciliation Engine - Database Setup

DROP TABLE IF EXISTS billing_rates CASCADE;
DROP TABLE IF EXISTS project_assignments CASCADE;
DROP TABLE IF EXISTS employee_hierarchy CASCADE;

-- Organization hierarchy (self-referencing tree)
CREATE TABLE employee_hierarchy (
    employee_id INTEGER PRIMARY KEY,
    manager_id INTEGER REFERENCES employee_hierarchy(employee_id),
    employee_name VARCHAR(100) NOT NULL,
    department VARCHAR(50) NOT NULL
);

INSERT INTO employee_hierarchy (employee_id, manager_id, employee_name, department) VALUES
(1, NULL, 'Alice', 'Engineering'),
(2, 1, 'Bob', 'Engineering'),
(3, 1, 'Carol', 'Sales'),
(4, 2, 'Dave', 'Engineering'),
(5, 2, 'Eve', 'Engineering'),
(6, 4, 'Frank', 'Engineering'),
(7, 4, 'Grace', 'Engineering'),
(8, 5, 'Hank', 'Engineering'),
(9, 3, 'Ivy', 'Sales'),
(10, 9, 'Jack', 'Sales');

-- Project assignments with intentional overlaps, adjacent intervals, and containment
CREATE TABLE project_assignments (
    assignment_id SERIAL PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employee_hierarchy(employee_id),
    project_id INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL
);

INSERT INTO project_assignments (employee_id, project_id, start_date, end_date) VALUES
-- Frank (6), Project 101: chain overlap + adjacent + fully contained
(6, 101, '2024-01-01', '2024-01-15'),
(6, 101, '2024-01-10', '2024-01-25'),
(6, 101, '2024-01-26', '2024-02-10'),
(6, 101, '2024-01-05', '2024-01-12'),
-- Frank (6), Project 102: single interval, overlaps with merged P101
(6, 102, '2024-01-20', '2024-02-05'),
-- Grace (7), Project 101: two intervals with gap
(7, 101, '2024-01-05', '2024-01-20'),
(7, 101, '2024-02-01', '2024-02-15'),
-- Grace (7), Project 103: overlaps with first Grace P101
(7, 103, '2024-01-15', '2024-01-25'),
-- Hank (8), Project 102: adjacent intervals
(8, 102, '2024-01-01', '2024-01-31'),
(8, 102, '2024-02-01', '2024-02-28'),
-- Hank (8), Project 103: separate from P102 (leap year gap on Feb 29)
(8, 103, '2024-03-01', '2024-03-15'),
-- Jack (10), Project 104: gap between intervals
(10, 104, '2024-01-01', '2024-01-15'),
(10, 104, '2024-01-20', '2024-01-31'),
-- Jack (10), Project 105: no overlap with P104
(10, 105, '2024-02-01', '2024-02-15');

-- Billing rates (SCD Type 2)
CREATE TABLE billing_rates (
    employee_id INTEGER NOT NULL REFERENCES employee_hierarchy(employee_id),
    hourly_rate NUMERIC(10,2) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NOT NULL
);

INSERT INTO billing_rates (employee_id, hourly_rate, effective_from, effective_to) VALUES
(6, 75.00, '2024-01-01', '2024-01-31'),
(6, 85.00, '2024-02-01', '9999-12-31'),
(7, 80.00, '2024-01-01', '2024-01-14'),
(7, 90.00, '2024-01-15', '9999-12-31'),
(8, 70.00, '2024-01-01', '2024-02-14'),
(8, 75.00, '2024-02-15', '9999-12-31'),
(10, 60.00, '2024-01-01', '9999-12-31');
