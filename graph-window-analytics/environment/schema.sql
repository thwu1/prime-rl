
-- Network graph schema and seed data
-- Directed weighted graph representing a communication network

CREATE TABLE node (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    region TEXT NOT NULL,
    capacity INTEGER NOT NULL
);

CREATE TABLE edge (
    src INTEGER NOT NULL REFERENCES node(id),
    dst INTEGER NOT NULL REFERENCES node(id),
    weight REAL NOT NULL CHECK(weight > 0),
    edge_type TEXT NOT NULL CHECK(edge_type IN ('primary', 'secondary', 'backup')),
    PRIMARY KEY(src, dst)
);

-- Note: no index on edge(dst) by default; only PRIMARY KEY index on (src, dst)

INSERT INTO node VALUES
(1,  'hub-alpha-1',   'alpha', 100),
(2,  'hub-alpha-2',   'alpha', 75),
(3,  'hub-alpha-3',   'alpha', 120),
(4,  'hub-alpha-4',   'alpha', 60),
(5,  'relay-beta-1',  'beta',  90),
(6,  'relay-beta-2',  'beta',  110),
(7,  'relay-beta-3',  'beta',  80),
(8,  'core-gamma-1',  'gamma', 150),
(9,  'core-gamma-2',  'gamma', 95),
(10, 'core-gamma-3',  'gamma', 130);

INSERT INTO edge VALUES
-- Alpha internal links
(1, 2, 2.0,  'primary'),
(2, 3, 3.0,  'primary'),
(3, 4, 1.0,  'primary'),
(4, 1, 5.0,  'backup'),
(1, 3, 4.0,  'secondary'),
(2, 4, 5.0,  'backup'),
-- Alpha to Beta cross-region
(3, 5, 6.0,  'primary'),
(4, 6, 3.0,  'secondary'),
-- Beta internal links
(5, 6, 2.0,  'primary'),
(6, 7, 4.0,  'primary'),
(7, 5, 3.0,  'backup'),
(5, 7, 7.0,  'secondary'),
-- Beta to Gamma cross-region
(5, 8, 5.0,  'primary'),
(7, 9, 2.0,  'secondary'),
-- Gamma internal links
(8, 9, 1.0,  'primary'),
(9, 10, 3.0, 'primary'),
(10, 8, 4.0, 'backup'),
(8, 10, 6.0, 'secondary');
-- No gamma-to-alpha or gamma-to-beta edges: gamma is a sink region
