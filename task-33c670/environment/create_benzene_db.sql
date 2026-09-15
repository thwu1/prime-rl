CREATE TABLE benzene_monitoring (
    sample_id TEXT PRIMARY KEY,
    well_id TEXT NOT NULL,
    sample_date TEXT NOT NULL,
    result REAL NOT NULL,
    detection_limit REAL NOT NULL,
    detect_flag INTEGER NOT NULL
);

INSERT INTO benzene_monitoring VALUES ('BZ-001', 'MW-4', '2023-01-12', 0.5, 0.5, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-002', 'MW-4', '2023-01-26', 1.2, 0.5, 1);
INSERT INTO benzene_monitoring VALUES ('BZ-003', 'MW-4', '2023-02-09', 0.5, 0.5, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-004', 'MW-4', '2023-02-23', 2.8, 0.5, 1);
INSERT INTO benzene_monitoring VALUES ('BZ-005', 'MW-4', '2023-03-09', 1.0, 1.0, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-006', 'MW-4', '2023-03-23', 0.5, 0.5, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-007', 'MW-4', '2023-04-06', 5.0, 0.5, 1);
INSERT INTO benzene_monitoring VALUES ('BZ-008', 'MW-4', '2023-04-20', 0.5, 0.5, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-009', 'MW-4', '2023-05-04', 1.0, 1.0, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-010', 'MW-4', '2023-05-18', 1.5, 0.5, 1);
INSERT INTO benzene_monitoring VALUES ('BZ-011', 'MW-4', '2023-06-01', 0.5, 0.5, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-012', 'MW-4', '2023-06-15', 10.0, 0.5, 1);
INSERT INTO benzene_monitoring VALUES ('BZ-013', 'MW-4', '2023-06-29', 1.0, 1.0, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-014', 'MW-4', '2023-07-13', 3.5, 0.5, 1);
INSERT INTO benzene_monitoring VALUES ('BZ-015', 'MW-4', '2023-07-27', 0.5, 0.5, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-016', 'MW-4', '2023-08-10', 7.0, 0.5, 1);
INSERT INTO benzene_monitoring VALUES ('BZ-017', 'MW-4', '2023-08-24', 2.0, 0.5, 1);
INSERT INTO benzene_monitoring VALUES ('BZ-018', 'MW-4', '2023-09-07', 0.5, 0.5, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-019', 'MW-4', '2023-09-21', 1.0, 1.0, 0);
INSERT INTO benzene_monitoring VALUES ('BZ-020', 'MW-4', '2023-10-05', 15.0, 0.5, 1);
