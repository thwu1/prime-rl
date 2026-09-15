
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS projects (
    id int PRIMARY KEY,
    parent_id int REFERENCES projects(id),
    name text NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_allocations (
    id serial PRIMARY KEY,
    server_id text NOT NULL,
    datacenter text NOT NULL,
    project_id int NOT NULL REFERENCES projects(id),
    event_date date NOT NULL,
    daily_cost numeric(10,2) NOT NULL
);

-- Project hierarchy
--   Infrastructure (1)
--     Compute (2)
--       ML Training (5)
--       Batch Jobs (6)
--     Storage (3)
--       Backups (7)
--       Archives (8)
--   Applications (4)
--     Web Frontend (9)
--     API Backend (10)
--       Auth Service (11)
--       Data Pipeline (12)

INSERT INTO projects (id, parent_id, name) VALUES
(1, NULL, 'Infrastructure'),
(2, 1, 'Compute'),
(3, 1, 'Storage'),
(4, NULL, 'Applications'),
(5, 2, 'ML Training'),
(6, 2, 'Batch Jobs'),
(7, 3, 'Backups'),
(8, 3, 'Archives'),
(9, 4, 'Web Frontend'),
(10, 4, 'API Backend'),
(11, 10, 'Auth Service'),
(12, 10, 'Data Pipeline')
ON CONFLICT (id) DO NOTHING;

-- Raw allocation events: each row = server assigned to project starting on event_date
-- A new row for the same server supersedes the previous assignment.

TRUNCATE raw_allocations RESTART IDENTITY CASCADE;

INSERT INTO raw_allocations (server_id, datacenter, project_id, event_date, daily_cost) VALUES
-- srv-001 (US-EAST): costs 10 -> 8(drop) -> 12 -> 15
('srv-001', 'US-EAST', 5,  '2023-01-01', 10.00),
('srv-001', 'US-EAST', 6,  '2023-03-15', 8.00),
('srv-001', 'US-EAST', 5,  '2023-06-01', 12.00),
('srv-001', 'US-EAST', 11, '2023-09-01', 15.00),
-- srv-002 (US-EAST): costs 8 -> 11
('srv-002', 'US-EAST', 9,  '2023-01-15', 8.00),
('srv-002', 'US-EAST', 12, '2023-07-01', 11.00),
-- srv-003 (US-EAST): costs 6 -> 9(rise) -> 7(drop) -> 10 -> 13(rise) -> 11(drop) -> 14
('srv-003', 'US-EAST', 7,  '2023-02-01', 6.00),
('srv-003', 'US-EAST', 8,  '2023-04-01', 9.00),
('srv-003', 'US-EAST', 7,  '2023-05-01', 7.00),
('srv-003', 'US-EAST', 5,  '2023-08-01', 10.00),
('srv-003', 'US-EAST', 6,  '2023-10-01', 13.00),
('srv-003', 'US-EAST', 5,  '2023-11-01', 11.00),
('srv-003', 'US-EAST', 6,  '2023-12-01', 14.00),
-- srv-004 (US-EAST): costs 15 -> 12(drop)
('srv-004', 'US-EAST', 11, '2023-03-01', 15.00),
('srv-004', 'US-EAST', 12, '2023-12-15', 12.00),
-- srv-005 (US-EAST): costs 20 -> 22 -> 25 -> 28 (all rising)
('srv-005', 'US-EAST', 5,  '2023-01-01', 20.00),
('srv-005', 'US-EAST', 6,  '2023-04-01', 22.00),
('srv-005', 'US-EAST', 9,  '2023-07-01', 25.00),
('srv-005', 'US-EAST', 12, '2023-10-01', 28.00),
-- srv-006 (EU-WEST): costs 9 -> 7(drop) -> 10
('srv-006', 'EU-WEST', 9,  '2023-01-01', 9.00),
('srv-006', 'EU-WEST', 11, '2023-06-01', 7.00),
('srv-006', 'EU-WEST', 9,  '2023-09-01', 10.00),
-- srv-007 (EU-WEST): costs 11 -> 14(rise) -> 13(drop) -> 16
('srv-007', 'EU-WEST', 12, '2023-02-01', 11.00),
('srv-007', 'EU-WEST', 5,  '2023-05-01', 14.00),
('srv-007', 'EU-WEST', 6,  '2023-08-01', 13.00),
('srv-007', 'EU-WEST', 12, '2023-11-01', 16.00),
-- srv-008 (EU-WEST): costs 7 -> 7 (same = non-decreasing)
('srv-008', 'EU-WEST', 7,  '2023-01-01', 7.00),
('srv-008', 'EU-WEST', 8,  '2023-12-01', 7.00),
-- srv-009 (EU-WEST): costs 16 -> 14(drop) -> 18 -> 20
('srv-009', 'EU-WEST', 5,  '2023-03-01', 16.00),
('srv-009', 'EU-WEST', 6,  '2023-06-01', 14.00),
('srv-009', 'EU-WEST', 5,  '2023-09-01', 18.00),
('srv-009', 'EU-WEST', 11, '2023-12-01', 20.00),
-- srv-010 (EU-WEST): costs 5 -> 6(rise) -> 4(drop) -> 8(rise) -> 3(drop)
('srv-010', 'EU-WEST', 8,  '2023-01-01', 5.00),
('srv-010', 'EU-WEST', 7,  '2023-03-01', 6.00),
('srv-010', 'EU-WEST', 8,  '2023-06-01', 4.00),
('srv-010', 'EU-WEST', 7,  '2023-09-01', 8.00),
('srv-010', 'EU-WEST', 8,  '2023-12-01', 3.00);
