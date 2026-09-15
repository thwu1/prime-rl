-- Baseline performance data from healthy period (2024-06-08, one week before incident)
-- Database: ECOM_PROD, Instance: ecom1

CREATE TABLE sysstat (
    statistic_id INTEGER,
    name TEXT,
    value INTEGER
);

INSERT INTO sysstat VALUES (1, 'db block gets from cache', 2000000);
INSERT INTO sysstat VALUES (2, 'consistent gets from cache', 10000000);
INSERT INTO sysstat VALUES (3, 'physical reads cache', 300000);
INSERT INTO sysstat VALUES (4, 'physical reads direct', 20000);
INSERT INTO sysstat VALUES (5, 'physical writes direct', 15000);
INSERT INTO sysstat VALUES (6, 'parse count (total)', 1800000);
INSERT INTO sysstat VALUES (7, 'parse count (hard)', 180000);
INSERT INTO sysstat VALUES (8, 'parse count (failures)', 50);
INSERT INTO sysstat VALUES (9, 'sorts (memory)', 80000);
INSERT INTO sysstat VALUES (10, 'sorts (disk)', 500);
INSERT INTO sysstat VALUES (11, 'table scans (long tables)', 1200);
INSERT INTO sysstat VALUES (12, 'table scans (short tables)', 400000);
INSERT INTO sysstat VALUES (13, 'table fetch by rowid', 4800000);
INSERT INTO sysstat VALUES (14, 'execute count', 3200000);
INSERT INTO sysstat VALUES (15, 'user commits', 750000);
INSERT INTO sysstat VALUES (16, 'user rollbacks', 2000);
INSERT INTO sysstat VALUES (17, 'redo size', 12000000000);
INSERT INTO sysstat VALUES (18, 'session logical reads', 12020000);
INSERT INTO sysstat VALUES (19, 'CPU used by this session', 25000000);
INSERT INTO sysstat VALUES (20, 'recursive calls', 5000000);
INSERT INTO sysstat VALUES (21, 'workarea executions - optimal', 90000);
INSERT INTO sysstat VALUES (22, 'workarea executions - onepass', 8000);
INSERT INTO sysstat VALUES (23, 'workarea executions - multipass', 2000);

CREATE TABLE system_event (
    event TEXT,
    waits INTEGER,
    time_waited_micro INTEGER,
    avg_wait_micro INTEGER,
    wait_class TEXT
);

INSERT INTO system_event VALUES ('db file sequential read', 500000, 2500000000, 5000, 'User I/O');
INSERT INTO system_event VALUES ('latch: shared pool', 50000, 250000000, 5000, 'Concurrency');
INSERT INTO system_event VALUES ('direct path read temp', 10000, 200000000, 20000, 'User I/O');
INSERT INTO system_event VALUES ('direct path write temp', 8000, 160000000, 20000, 'User I/O');
INSERT INTO system_event VALUES ('log file sync', 450000, 1350000000, 3000, 'Commit');
INSERT INTO system_event VALUES ('db file scattered read', 80000, 400000000, 5000, 'User I/O');
INSERT INTO system_event VALUES ('latch: cache buffers chains', 30000, 60000000, 2000, 'Concurrency');
INSERT INTO system_event VALUES ('buffer busy waits', 10000, 40000000, 4000, 'Concurrency');
INSERT INTO system_event VALUES ('log file parallel write', 450000, 450000000, 1000, 'System I/O');
INSERT INTO system_event VALUES ('control file sequential read', 150000, 225000000, 1500, 'System I/O');
INSERT INTO system_event VALUES ('SQL*Net message from client', 4500000, 150000000000, 33333, 'Idle');
INSERT INTO system_event VALUES ('SQL*Net message to client', 4500000, 45000000, 10, 'Idle');

CREATE TABLE pgastat (
    name TEXT,
    value TEXT,
    unit TEXT
);

INSERT INTO pgastat VALUES ('aggregate PGA target parameter', '268435456', 'bytes');
INSERT INTO pgastat VALUES ('aggregate PGA auto target', '241591910', 'bytes');
INSERT INTO pgastat VALUES ('global memory bound', '53687091', 'bytes');
INSERT INTO pgastat VALUES ('total PGA inuse', '201326592', 'bytes');
INSERT INTO pgastat VALUES ('total PGA allocated', '234881024', 'bytes');
INSERT INTO pgastat VALUES ('maximum PGA allocated', '301989888', 'bytes');
INSERT INTO pgastat VALUES ('total extra bytes read/written', '52428800', 'bytes');
INSERT INTO pgastat VALUES ('cache hit percentage', '95.0', 'percent');
INSERT INTO pgastat VALUES ('recompute count (total)', '80000', '');
INSERT INTO pgastat VALUES ('over allocation count', '0', '');
