CREATE TABLE collections (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    format TEXT NOT NULL,
    base_path TEXT NOT NULL
);

CREATE TABLE targets (
    target_id TEXT PRIMARY KEY,
    collection_id TEXT NOT NULL,
    puzzle_ref TEXT NOT NULL,
    max_pushes INTEGER NOT NULL,
    time_limit_sec INTEGER NOT NULL,
    FOREIGN KEY (collection_id) REFERENCES collections(id)
);

INSERT INTO collections VALUES ('microban', 'Microban', 'xsb', '/app/collections/microban');
INSERT INTO collections VALUES ('benchlib', 'Benchmark Library', 'ssx', '/app/collections/benchlib.ssx');
INSERT INTO collections VALUES ('assorted', 'Assorted Puzzles', 'xsb', '/app/collections/assorted');

INSERT INTO targets VALUES ('T01', 'microban', 'mb_001.xsb', 15, 30);
INSERT INTO targets VALUES ('T02', 'microban', 'mb_004.xsb', 80, 60);
INSERT INTO targets VALUES ('T03', 'microban', 'mb_005.xsb', 100, 60);
INSERT INTO targets VALUES ('T04', 'microban', 'mb_010.xsb', 80, 60);
INSERT INTO targets VALUES ('T05', 'benchlib', 'P2', 50, 60);
INSERT INTO targets VALUES ('T06', 'benchlib', 'P4', 80, 60);
INSERT INTO targets VALUES ('T07', 'benchlib', 'P6', 150, 180);
INSERT INTO targets VALUES ('T08', 'assorted', 'cascade.xsb', 50, 60);
INSERT INTO targets VALUES ('T09', 'assorted', 'diamond.xsb', 80, 120);
INSERT INTO targets VALUES ('T10', 'assorted', 'crossroads.xsb', 200, 300);
