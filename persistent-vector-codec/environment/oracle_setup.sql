CREATE TABLE oracle (
    pool_file TEXT NOT NULL,
    vector_index INTEGER NOT NULL,
    reconstructed TEXT NOT NULL,
    PRIMARY KEY (pool_file, vector_index)
);

INSERT INTO oracle VALUES ('pool1.json', 0, '[10, 20, 30, 40]');
INSERT INTO oracle VALUES ('pool1.json', 1, '[10, 20, 30, 40, 50, 60]');
INSERT INTO oracle VALUES ('pool1.json', 4, '[10, 20, 30, 40, 50, 60, 70, 80, 90, 100]');
INSERT INTO oracle VALUES ('pool2.json', 0, '[1, 2, 3, 4, 5, 6, 7, 8]');
INSERT INTO oracle VALUES ('pool2.json', 3, '[100, 200, 300]');
INSERT INTO oracle VALUES ('pool3.json', 0, '[1, 2, 3, 4, 5, 6, 7, 8]');
