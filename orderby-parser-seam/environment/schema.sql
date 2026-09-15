-- Schema and seed data for the analytics database

CREATE TABLE nums (a INT);
INSERT INTO nums VALUES (0), (1), (2), (3);

CREATE TABLE inventory (
    id INT PRIMARY KEY,
    item TEXT NOT NULL,
    category TEXT NOT NULL,
    price INT NOT NULL,
    stock INT NOT NULL
);

INSERT INTO inventory VALUES
(1, 'Wrench', 'tools', 25, 100),
(2, 'Hammer', 'tools', 18, 150),
(3, 'Bolt', 'fasteners', 2, 5000),
(4, 'Nail', 'fasteners', 1, 8000),
(5, 'Wire', 'electrical', 10, 300),
(6, 'Switch', 'electrical', 15, 200),
(7, 'Pipe', 'plumbing', 30, 80),
(8, 'Valve', 'plumbing', 45, 60);
