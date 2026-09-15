-- postgres_air schema and data for booking search system

CREATE SCHEMA postgres_air;

-- ============================================================
-- Tables (in dependency order)
-- ============================================================

CREATE TABLE postgres_air.airport (
    airport_code char(3) PRIMARY KEY,
    airport_name text NOT NULL,
    city text NOT NULL,
    iso_country text NOT NULL
);

CREATE TABLE postgres_air.flight (
    flight_id serial PRIMARY KEY,
    flight_no text NOT NULL,
    departure_airport char(3) REFERENCES postgres_air.airport(airport_code),
    arrival_airport char(3) REFERENCES postgres_air.airport(airport_code),
    scheduled_departure timestamptz NOT NULL,
    scheduled_arrival timestamptz NOT NULL,
    actual_departure timestamptz,
    status text DEFAULT 'On schedule',
    update_ts timestamptz DEFAULT now()
);

CREATE TABLE postgres_air.booking (
    booking_id serial PRIMARY KEY,
    booking_ref text NOT NULL,
    booking_name text,
    email text,
    account_id int,
    update_ts timestamptz DEFAULT now()
);

CREATE TABLE postgres_air.booking_leg (
    booking_leg_id serial PRIMARY KEY,
    booking_id int REFERENCES postgres_air.booking(booking_id),
    flight_id int REFERENCES postgres_air.flight(flight_id),
    leg_num int DEFAULT 1,
    is_returning boolean DEFAULT false,
    update_ts timestamptz DEFAULT now()
);

CREATE TABLE postgres_air.passenger (
    passenger_id serial PRIMARY KEY,
    booking_id int REFERENCES postgres_air.booking(booking_id),
    passenger_no int DEFAULT 1,
    last_name text NOT NULL,
    first_name text NOT NULL,
    account_id int,
    age int
);

-- ============================================================
-- Reference data: 25 airports
-- ============================================================

INSERT INTO postgres_air.airport (airport_code, airport_name, city, iso_country) VALUES
('AMS', 'Schiphol', 'Amsterdam', 'NL'),
('ATL', 'Hartsfield-Jackson', 'Atlanta', 'US'),
('BKK', 'Suvarnabhumi', 'Bangkok', 'TH'),
('BOS', 'Logan Intl', 'Boston', 'US'),
('CDG', 'Charles de Gaulle', 'Paris', 'FR'),
('DEN', 'Denver Intl', 'Denver', 'US'),
('DFW', 'Dallas/Fort Worth', 'Dallas', 'US'),
('DXB', 'Dubai Intl', 'Dubai', 'AE'),
('FCO', 'Fiumicino', 'Rome', 'IT'),
('FRA', 'Frankfurt', 'Frankfurt', 'DE'),
('GRU', 'Guarulhos', 'Sao Paulo', 'BR'),
('HKG', 'Hong Kong Intl', 'Hong Kong', 'HK'),
('ICN', 'Incheon', 'Seoul', 'KR'),
('JFK', 'John F Kennedy Intl', 'New York', 'US'),
('LAX', 'Los Angeles Intl', 'Los Angeles', 'US'),
('LHR', 'Heathrow', 'London', 'GB'),
('MEX', 'Benito Juarez', 'Mexico City', 'MX'),
('MIA', 'Miami Intl', 'Miami', 'US'),
('NRT', 'Narita', 'Tokyo', 'JP'),
('ORD', 'O''Hare Intl', 'Chicago', 'US'),
('SEA', 'Seattle-Tacoma Intl', 'Seattle', 'US'),
('SFO', 'San Francisco Intl', 'San Francisco', 'US'),
('SIN', 'Changi', 'Singapore', 'SG'),
('SYD', 'Kingsford Smith', 'Sydney', 'AU'),
('YYZ', 'Toronto Pearson', 'Toronto', 'CA');

-- ============================================================
-- Lookup tables for deterministic data generation
-- ============================================================

CREATE TEMPORARY TABLE tmp_airports AS
    SELECT airport_code, (row_number() OVER (ORDER BY airport_code) - 1)::int AS idx
    FROM postgres_air.airport;

CREATE TEMPORARY TABLE tmp_first_names (idx int PRIMARY KEY, name text);
INSERT INTO tmp_first_names VALUES
(0,'John'),(1,'Jane'),(2,'Bob'),(3,'Alice'),(4,'Charlie'),
(5,'Diana'),(6,'Eve'),(7,'Frank'),(8,'Grace'),(9,'Henry'),
(10,'Iris'),(11,'Jack'),(12,'Kate'),(13,'Leo'),(14,'Mary'),
(15,'Nick'),(16,'Olivia'),(17,'Pat'),(18,'Quinn'),(19,'Rosa');

CREATE TEMPORARY TABLE tmp_last_names (idx int PRIMARY KEY, name text);
INSERT INTO tmp_last_names VALUES
(0,'Smith'),(1,'Johnson'),(2,'Williams'),(3,'Brown'),(4,'Jones'),
(5,'Garcia'),(6,'Miller'),(7,'Davis'),(8,'Rodriguez'),(9,'Martinez');

CREATE TEMPORARY TABLE tmp_domains (idx int PRIMARY KEY, name text);
INSERT INTO tmp_domains VALUES
(0,'gmail.com'),(1,'yahoo.com'),(2,'outlook.com'),(3,'mail.com'),(4,'proton.me');

-- ============================================================
-- Generate 15000 flights
-- ============================================================

INSERT INTO postgres_air.flight
    (flight_no, departure_airport, arrival_airport,
     scheduled_departure, scheduled_arrival, actual_departure, status)
SELECT
    'PA' || lpad(g::text, 4, '0'),
    dep.airport_code,
    arr.airport_code,
    '2024-01-01 00:00:00+00'::timestamptz
        + (((g * 37 + 13) % 366)) * interval '1 day'
        + ((g * 13) % 24) * interval '1 hour',
    '2024-01-01 00:00:00+00'::timestamptz
        + (((g * 37 + 13) % 366)) * interval '1 day'
        + ((g * 13) % 24 + 3) * interval '1 hour',
    CASE WHEN g % 10 != 0
        THEN '2024-01-01 00:00:00+00'::timestamptz
            + (((g * 37 + 13) % 366)) * interval '1 day'
            + ((g * 13) % 24) * interval '1 hour'
        ELSE NULL
    END,
    CASE WHEN g % 20 != 0 THEN 'On schedule' ELSE 'Canceled' END
FROM generate_series(1, 15000) g
JOIN tmp_airports dep ON dep.idx = ((g - 1) % 25)
JOIN tmp_airports arr ON arr.idx = (((g - 1) * 7 + 3) % 25);

-- ============================================================
-- Generate 25000 bookings
-- ============================================================

INSERT INTO postgres_air.booking
    (booking_ref, booking_name, email, update_ts)
SELECT
    upper(substr(md5(g::text), 1, 6)),
    ln.name,
    lower(fn.name) || '.' || lower(ln.name)
        || ((g - 1) % 1000)::text
        || '@' || d.name,
    '2024-01-01 00:00:00+00'::timestamptz
        + (((g * 41 + 7) % 366)) * interval '1 day'
FROM generate_series(1, 25000) g
JOIN tmp_first_names fn ON fn.idx = ((g - 1) % 20)
JOIN tmp_last_names  ln ON ln.idx = ((g - 1) % 10)
JOIN tmp_domains     d  ON d.idx  = ((g - 1) % 5);

-- ============================================================
-- Generate 35000 booking legs
-- ============================================================

INSERT INTO postgres_air.booking_leg
    (booking_id, flight_id, leg_num, is_returning)
SELECT
    1 + ((g - 1) % 25000),
    1 + ((g - 1) % 15000),
    CASE WHEN (g - 1) >= 25000 THEN 2 ELSE 1 END,
    (g - 1) >= 25000
FROM generate_series(1, 35000) g;

-- ============================================================
-- Generate 45000 passengers
-- ============================================================

INSERT INTO postgres_air.passenger
    (booking_id, passenger_no, last_name, first_name, age)
SELECT
    1 + ((g - 1) % 25000),
    1 + ((g - 1) / 25000),
    pln.name,
    pfn.name,
    18 + ((g * 11) % 60)
FROM generate_series(1, 45000) g
JOIN tmp_last_names  pln ON pln.idx = ((g * 3) % 10)
JOIN tmp_first_names pfn ON pfn.idx = ((g * 7) % 20);

-- ============================================================
-- Drop temporary lookup tables
-- ============================================================

DROP TABLE tmp_airports;
DROP TABLE tmp_first_names;
DROP TABLE tmp_last_names;
DROP TABLE tmp_domains;

-- ============================================================
-- Indexes
-- ============================================================

CREATE INDEX idx_flight_departure ON postgres_air.flight(departure_airport);
CREATE INDEX idx_flight_arrival ON postgres_air.flight(arrival_airport);
CREATE INDEX idx_flight_sched_dep ON postgres_air.flight(scheduled_departure);
CREATE INDEX idx_booking_leg_booking ON postgres_air.booking_leg(booking_id);
CREATE INDEX idx_booking_leg_flight ON postgres_air.booking_leg(flight_id);
CREATE INDEX idx_passenger_booking ON postgres_air.passenger(booking_id);
CREATE INDEX idx_passenger_last_name ON postgres_air.passenger(last_name);
CREATE INDEX idx_booking_email ON postgres_air.booking(email);
CREATE INDEX idx_booking_email_lower ON postgres_air.booking USING hash (lower(email));
CREATE INDEX idx_booking_update ON postgres_air.booking(update_ts);

-- ============================================================
-- Analyze all tables
-- ============================================================

ANALYZE postgres_air.airport;
ANALYZE postgres_air.flight;
ANALYZE postgres_air.booking;
ANALYZE postgres_air.booking_leg;
ANALYZE postgres_air.passenger;
