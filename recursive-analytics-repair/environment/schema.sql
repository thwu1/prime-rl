-- Transit Network Analytics Schema

CREATE TABLE IF NOT EXISTS stations (
    id INT PRIMARY KEY,
    name TEXT NOT NULL,
    zone TEXT NOT NULL,
    elevation INT
);

CREATE TABLE IF NOT EXISTS connections (
    from_id INT REFERENCES stations(id),
    to_id INT REFERENCES stations(id),
    distance NUMERIC(6,1) NOT NULL,
    travel_time INT NOT NULL,
    line TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, line)
);

CREATE TABLE IF NOT EXISTS ridership (
    station_id INT REFERENCES stations(id),
    ride_date DATE NOT NULL,
    hour INT NOT NULL CHECK (hour >= 0 AND hour < 24),
    passengers INT NOT NULL,
    fare_revenue NUMERIC(10,2) NOT NULL
);

-- Station data: 6 stations across 3 zones
INSERT INTO stations VALUES
(1, 'Central',    'downtown', 50),
(2, 'North Park', 'uptown',   120),
(3, 'East End',   'downtown', 45),
(4, 'West Gate',  'midtown',  80),
(5, 'South Bay',  'downtown', 30),
(6, 'Hill Top',   'uptown',   200);

-- Directed graph with cycles: 1<->2, 1<->3, 3<->5
-- Station 4 reachable only via 1->3->5->4
-- Station 6 reachable only via 1->2->6
INSERT INTO connections VALUES
(1, 2, 5.0,  12, 'Red'),
(1, 3, 3.0,  8,  'Blue'),
(2, 1, 5.0,  12, 'Red'),
(2, 6, 6.0,  15, 'Red'),
(3, 5, 2.5,  6,  'Blue'),
(3, 1, 3.0,  8,  'Blue'),
(4, 1, 4.5,  10, 'Green'),
(5, 3, 2.5,  6,  'Blue'),
(5, 4, 7.0,  18, 'Yellow'),
(6, 2, 6.0,  15, 'Red');

-- Ridership: 3 days, varying hours, multiple records per station-day
INSERT INTO ridership VALUES
(1, '2024-01-01',  8,  500,  7500.00),
(1, '2024-01-01', 14,  600,  9000.00),
(1, '2024-01-02',  8,  520,  7800.00),
(1, '2024-01-02', 14,  580,  8700.00),
(1, '2024-01-03',  8,  510,  7650.00),
(1, '2024-01-03', 14,  620,  9300.00),
(2, '2024-01-01',  8,  300,  4500.00),
(2, '2024-01-01', 14,  350,  5250.00),
(2, '2024-01-02',  8,  310,  4650.00),
(2, '2024-01-02', 14,  340,  5100.00),
(2, '2024-01-03',  8,  320,  4800.00),
(3, '2024-01-01',  8,  200,  3000.00),
(3, '2024-01-02', 14,  250,  3750.00),
(3, '2024-01-03',  8,  220,  3300.00),
(4, '2024-01-01',  8,  400,  6000.00),
(4, '2024-01-02',  8,  420,  6300.00),
(4, '2024-01-02', 14,  380,  5700.00),
(4, '2024-01-03', 14,  410,  6150.00),
(5, '2024-01-01',  8,  150,  2250.00),
(5, '2024-01-02',  8,  160,  2400.00),
(5, '2024-01-03',  8,  140,  2100.00),
(6, '2024-01-01', 14,  280,  4200.00),
(6, '2024-01-02',  8,  290,  4350.00),
(6, '2024-01-03', 14,  270,  4050.00);
