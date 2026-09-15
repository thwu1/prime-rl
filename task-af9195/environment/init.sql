CREATE TABLE instances (
    name TEXT PRIMARY KEY,
    num_peaks INTEGER NOT NULL,
    dimension INTEGER NOT NULL,
    change_frequency INTEGER NOT NULL,
    shift_severity REAL NOT NULL,
    num_environments INTEGER NOT NULL,
    seed INTEGER NOT NULL
);

CREATE TABLE thresholds (
    name TEXT PRIMARY KEY,
    max_offline_error REAL NOT NULL
);

INSERT INTO instances VALUES ('F1', 10, 5, 5000, 1.0, 20, 100);
INSERT INTO instances VALUES ('F2', 10, 5, 5000, 3.0, 20, 200);
INSERT INTO instances VALUES ('F3', 25, 5, 5000, 1.0, 20, 300);
INSERT INTO instances VALUES ('F4', 10, 5, 2500, 2.0, 20, 400);
INSERT INTO instances VALUES ('F5', 10, 5, 1000, 3.0, 20, 500);
INSERT INTO instances VALUES ('F6', 10, 10, 5000, 2.0, 20, 600);

INSERT INTO thresholds VALUES ('F1', 5.0);
INSERT INTO thresholds VALUES ('F2', 8.0);
INSERT INTO thresholds VALUES ('F3', 7.0);
INSERT INTO thresholds VALUES ('F4', 8.0);
INSERT INTO thresholds VALUES ('F5', 15.0);
INSERT INTO thresholds VALUES ('F6', 10.0);
