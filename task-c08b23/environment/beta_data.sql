-- Processor Beta evaluation results database
-- Schema differs from the CSV format used for Alpha results

CREATE TABLE evaluation_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO evaluation_metadata VALUES ('processor_name', 'Beta-rv64');
INSERT INTO evaluation_metadata VALUES ('evaluation_date', '2024-01-15');
INSERT INTO evaluation_metadata VALUES ('target_os', 'Debian');
INSERT INTO evaluation_metadata VALUES ('evaluator', 'BESSPIN Tool Suite v3.1');
INSERT INTO evaluation_metadata VALUES ('notes', 'Re-evaluation after firmware update; run_id=1 results superseded');

CREATE TABLE test_scores (
    vulnerability_class TEXT NOT NULL,
    cwe_id TEXT NOT NULL,
    test_part INTEGER NOT NULL,
    result TEXT NOT NULL,
    run_id INTEGER NOT NULL DEFAULT 1,
    valid INTEGER NOT NULL DEFAULT 1
);

-- Superseded results from initial run (run_id=1, valid=0)
-- These were invalidated after a firmware configuration issue was discovered
INSERT INTO test_scores VALUES ('resourceManagement', '416', 1, 'HIGH', 1, 0);
INSERT INTO test_scores VALUES ('resourceManagement', '416', 2, 'HIGH', 1, 0);
INSERT INTO test_scores VALUES ('informationLeakage', '200', 1, 'NONE', 1, 0);
INSERT INTO test_scores VALUES ('informationLeakage', '200', 2, 'NONE', 1, 0);
INSERT INTO test_scores VALUES ('injection', 'INJ_1', 1, 'NONE', 1, 0);
INSERT INTO test_scores VALUES ('injection', 'INJ_2', 1, 'NONE', 1, 0);

-- Valid results from corrected run (run_id=2, valid=1)

-- bufferErrors
INSERT INTO test_scores VALUES ('bufferErrors', '118', 1, 'HIGH', 2, 1);
INSERT INTO test_scores VALUES ('bufferErrors', '119', 1, 'LOW', 2, 1);
INSERT INTO test_scores VALUES ('bufferErrors', '120', 1, 'NONE', 2, 1);
INSERT INTO test_scores VALUES ('bufferErrors', '120', 2, 'LOW', 2, 1);
INSERT INTO test_scores VALUES ('bufferErrors', '121', 1, 'MED', 2, 1);
INSERT INTO test_scores VALUES ('bufferErrors', '122', 1, 'NONE', 2, 1);
INSERT INTO test_scores VALUES ('bufferErrors', '125', 1, 'MED', 2, 1);
INSERT INTO test_scores VALUES ('bufferErrors', '787', 1, 'NONE', 2, 1);
INSERT INTO test_scores VALUES ('bufferErrors', '787', 2, 'LOW', 2, 1);

-- PPAC
INSERT INTO test_scores VALUES ('PPAC', 'PPAC_1', 1, 'HIGH', 2, 1);
INSERT INTO test_scores VALUES ('PPAC', 'PPAC_2', 1, 'HIGH', 2, 1);
INSERT INTO test_scores VALUES ('PPAC', 'PPAC_3', 1, 'MED', 2, 1);

-- resourceManagement
INSERT INTO test_scores VALUES ('resourceManagement', '415', 1, 'MED', 2, 1);
INSERT INTO test_scores VALUES ('resourceManagement', '416', 1, 'LOW', 2, 1);
INSERT INTO test_scores VALUES ('resourceManagement', '416', 2, 'NONE', 2, 1);
INSERT INTO test_scores VALUES ('resourceManagement', '476', 1, 'NONE', 2, 1);
INSERT INTO test_scores VALUES ('resourceManagement', '588', 1, 'HIGH', 2, 1);
INSERT INTO test_scores VALUES ('resourceManagement', '590', 1, 'CALL_ERR', 2, 1);
INSERT INTO test_scores VALUES ('resourceManagement', '590', 2, 'FAIL', 2, 1);
INSERT INTO test_scores VALUES ('resourceManagement', '762', 1, 'CALL_ERR', 2, 1);

-- informationLeakage
INSERT INTO test_scores VALUES ('informationLeakage', '200', 1, 'LOW', 2, 1);
INSERT INTO test_scores VALUES ('informationLeakage', '200', 2, 'NONE', 2, 1);
INSERT INTO test_scores VALUES ('informationLeakage', '203', 1, 'NONE', 2, 1);
INSERT INTO test_scores VALUES ('informationLeakage', '212', 1, 'NONE', 2, 1);

-- numericErrors
INSERT INTO test_scores VALUES ('numericErrors', '190', 1, 'MED', 2, 1);
INSERT INTO test_scores VALUES ('numericErrors', '191', 1, 'MED', 2, 1);
INSERT INTO test_scores VALUES ('numericErrors', '456', 1, 'MED', 2, 1);
INSERT INTO test_scores VALUES ('numericErrors', '456', 2, 'MED', 2, 1);
INSERT INTO test_scores VALUES ('numericErrors', '456', 3, 'HIGH', 2, 1);
INSERT INTO test_scores VALUES ('numericErrors', '369', 1, 'NONE', 2, 1);
INSERT INTO test_scores VALUES ('numericErrors', '681', 1, 'LOW', 2, 1);

-- hardwareSoC
INSERT INTO test_scores VALUES ('hardwareSoC', '1037', 1, 'NOT_APPLICABLE', 2, 1);
INSERT INTO test_scores VALUES ('hardwareSoC', '1050', 1, 'NOT_APPLICABLE', 2, 1);
INSERT INTO test_scores VALUES ('hardwareSoC', '1256', 1, 'NOT_APPLICABLE', 2, 1);

-- injection
INSERT INTO test_scores VALUES ('injection', 'INJ_1', 1, 'LOW', 2, 1);
INSERT INTO test_scores VALUES ('injection', 'INJ_2', 1, 'MED', 2, 1);
INSERT INTO test_scores VALUES ('injection', 'INJ_3', 1, 'NONE', 2, 1);

CREATE INDEX idx_valid ON test_scores(valid);
CREATE INDEX idx_class_valid ON test_scores(vulnerability_class, valid);
