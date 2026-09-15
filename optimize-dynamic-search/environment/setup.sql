
-- PostgreSQL postgres_air database setup
SET timezone = 'UTC';

------------------------------------------------------------
-- SCHEMA
------------------------------------------------------------

CREATE TABLE airport (
    airport_code char(3) PRIMARY KEY,
    airport_name text NOT NULL,
    city text NOT NULL,
    iso_country text NOT NULL
);

CREATE TABLE flight (
    flight_id serial PRIMARY KEY,
    flight_no text NOT NULL,
    departure_airport char(3) NOT NULL REFERENCES airport(airport_code),
    arrival_airport char(3) NOT NULL REFERENCES airport(airport_code),
    scheduled_departure timestamptz NOT NULL,
    scheduled_arrival timestamptz NOT NULL,
    actual_departure timestamptz,
    status text NOT NULL DEFAULT 'On schedule',
    update_ts timestamptz DEFAULT now()
);

CREATE TABLE account (
    account_id serial PRIMARY KEY,
    login text,
    first_name text,
    last_name text
);

CREATE TABLE booking (
    booking_id serial PRIMARY KEY,
    booking_ref text NOT NULL,
    booking_name text,
    email text,
    account_id integer REFERENCES account(account_id),
    update_ts timestamptz DEFAULT now()
);

CREATE TABLE booking_leg (
    booking_leg_id serial PRIMARY KEY,
    booking_id integer NOT NULL REFERENCES booking(booking_id),
    flight_id integer NOT NULL REFERENCES flight(flight_id),
    leg_num integer NOT NULL DEFAULT 1,
    is_returning boolean DEFAULT false,
    update_ts timestamptz DEFAULT now()
);

CREATE TABLE passenger (
    passenger_id serial PRIMARY KEY,
    booking_id integer NOT NULL REFERENCES booking(booking_id),
    passenger_no integer NOT NULL DEFAULT 1,
    last_name text NOT NULL,
    first_name text NOT NULL,
    account_id integer,
    age integer
);

------------------------------------------------------------
-- DATA: Airports (30 real-world airports)
------------------------------------------------------------

INSERT INTO airport (airport_code, airport_name, city, iso_country) VALUES
('AMS', 'Schiphol', 'Amsterdam', 'NL'),
('ATL', 'Hartsfield-Jackson', 'Atlanta', 'US'),
('BKK', 'Suvarnabhumi', 'Bangkok', 'TH'),
('BOS', 'Logan Intl', 'Boston', 'US'),
('CDG', 'Charles de Gaulle', 'Paris', 'FR'),
('DEL', 'Indira Gandhi', 'New Delhi', 'IN'),
('DEN', 'Denver Intl', 'Denver', 'US'),
('DFW', 'Dallas Fort Worth', 'Dallas', 'US'),
('DXB', 'Dubai Intl', 'Dubai', 'AE'),
('FCO', 'Leonardo da Vinci', 'Rome', 'IT'),
('FRA', 'Frankfurt Intl', 'Frankfurt', 'DE'),
('GRU', 'Guarulhos Intl', 'Sao Paulo', 'BR'),
('HKG', 'Hong Kong Intl', 'Hong Kong', 'HK'),
('ICN', 'Incheon Intl', 'Seoul', 'KR'),
('IST', 'Istanbul', 'Istanbul', 'TR'),
('JFK', 'John F Kennedy Intl', 'New York', 'US'),
('LAX', 'Los Angeles Intl', 'Los Angeles', 'US'),
('LHR', 'Heathrow', 'London', 'GB'),
('MAD', 'Barajas', 'Madrid', 'ES'),
('MEX', 'Benito Juarez', 'Mexico City', 'MX'),
('MIA', 'Miami Intl', 'Miami', 'US'),
('MUC', 'Munich', 'Munich', 'DE'),
('NRT', 'Narita Intl', 'Tokyo', 'JP'),
('ORD', 'O''Hare Intl', 'Chicago', 'US'),
('PEK', 'Beijing Capital', 'Beijing', 'CN'),
('SEA', 'Seattle-Tacoma Intl', 'Seattle', 'US'),
('SFO', 'San Francisco Intl', 'San Francisco', 'US'),
('SIN', 'Changi', 'Singapore', 'SG'),
('SYD', 'Sydney Kingsford', 'Sydney', 'AU'),
('YYZ', 'Toronto Pearson', 'Toronto', 'CA');

------------------------------------------------------------
-- DATA: Build airport lookup for deterministic assignment
------------------------------------------------------------

CREATE TEMP TABLE numbered_airports AS
SELECT airport_code, (row_number() OVER (ORDER BY airport_code))::int AS rn
FROM airport;

------------------------------------------------------------
-- DATA: Flights (30,000)
------------------------------------------------------------

INSERT INTO flight (flight_no, departure_airport, arrival_airport,
                    scheduled_departure, scheduled_arrival, actual_departure, status)
SELECT
    'FL' || lpad(gs::text, 5, '0'),
    dep.airport_code,
    arr.airport_code,
    '2023-01-01 00:00:00+00'::timestamptz
        + ((gs - 1) % 365) * interval '1 day'
        + ((gs - 1) % 24) * interval '1 hour',
    '2023-01-01 00:00:00+00'::timestamptz
        + ((gs - 1) % 365) * interval '1 day'
        + ((gs - 1) % 24 + 2 + (gs - 1) % 6) * interval '1 hour',
    CASE WHEN gs % 20 = 0 THEN NULL
         ELSE '2023-01-01 00:00:00+00'::timestamptz
              + ((gs - 1) % 365) * interval '1 day'
              + ((gs - 1) % 24) * interval '1 hour'
              + (gs % 30) * interval '1 minute'
    END,
    CASE WHEN gs % 50 = 0 THEN 'Canceled'
         WHEN gs % 20 = 0 THEN 'On schedule'
         ELSE 'Completed' END
FROM generate_series(1, 30000) gs
JOIN numbered_airports dep ON dep.rn = 1 + (gs - 1) % 30
JOIN numbered_airports arr ON arr.rn = 1 + (gs * 7 + gs / 30 + 3) % 30;

------------------------------------------------------------
-- DATA: Accounts (5,000)
------------------------------------------------------------

INSERT INTO account (login, first_name, last_name)
SELECT
    'user' || i || '@example.com',
    (ARRAY['John','Jane','Bob','Alice','Charlie',
           'Diana','Eve','Frank','Grace','Hank',
           'Ivy','Jack','Karen','Leo','Mona',
           'Nick','Olivia','Paul','Quinn','Rosa'])[1 + i % 20],
    (ARRAY['Smith','Johnson','Williams','Brown','Jones',
           'Garcia','Miller','Davis','Wilson','Moore',
           'Taylor','Anderson','Thomas','Jackson','White',
           'Harris','Martin','Thompson','Robinson','Clark'])[1 + i % 20]
FROM generate_series(1, 5000) AS i;

------------------------------------------------------------
-- DATA: Bookings (60,000)
------------------------------------------------------------

INSERT INTO booking (booking_ref, booking_name, email, account_id)
SELECT
    'BK' || lpad(i::text, 7, '0'),
    (ARRAY['Smith','Johnson','Williams','Brown','Jones',
           'Garcia','Miller','Davis','Wilson','Moore',
           'Taylor','Anderson','Thomas','Jackson','White',
           'Harris','Martin','Thompson','Robinson','Clark'])[1 + i % 20]
        || ' booking',
    lower(
        (ARRAY['john','jane','bob','alice','charlie',
               'diana','eve','frank','grace','hank',
               'ivy','jack','karen','leo','mona',
               'nick','olivia','paul','quinn','rosa'])[1 + i % 20]
        || '.' ||
        (ARRAY['smith','johnson','williams','brown','jones',
               'garcia','miller','davis','wilson','moore',
               'taylor','anderson','thomas','jackson','white',
               'harris','martin','thompson','robinson','clark'])[1 + i % 20]
        || (i % 100)::text || '@'
        || (ARRAY['gmail.com','yahoo.com','outlook.com','company.org','airline.net'])[1 + i % 5]
    ),
    1 + i % 5000
FROM generate_series(1, 60000) AS i;

------------------------------------------------------------
-- DATA: Booking Legs - primary outbound leg (60,000)
------------------------------------------------------------

INSERT INTO booking_leg (booking_id, flight_id, leg_num, is_returning)
SELECT
    booking_id,
    1 + (booking_id - 1) % 30000,
    1,
    false
FROM booking;

------------------------------------------------------------
-- DATA: Booking Legs - return legs for ~33% of bookings (20,000)
------------------------------------------------------------

INSERT INTO booking_leg (booking_id, flight_id, leg_num, is_returning)
SELECT
    booking_id,
    1 + (booking_id * 7 + 10) % 30000,
    2,
    true
FROM booking
WHERE booking_id % 3 = 0;

------------------------------------------------------------
-- DATA: Passengers - primary passenger per booking (60,000)
------------------------------------------------------------

INSERT INTO passenger (booking_id, passenger_no, last_name, first_name, age)
SELECT
    booking_id,
    1,
    (ARRAY['Smith','Johnson','Williams','Brown','Jones',
           'Garcia','Miller','Davis','Wilson','Moore',
           'Taylor','Anderson','Thomas','Jackson','White',
           'Harris','Martin','Thompson','Robinson','Clark'])[1 + booking_id % 20],
    (ARRAY['John','Jane','Bob','Alice','Charlie',
           'Diana','Eve','Frank','Grace','Hank',
           'Ivy','Jack','Karen','Leo','Mona',
           'Nick','Olivia','Paul','Quinn','Rosa'])[1 + booking_id % 20],
    18 + (booking_id % 60)
FROM booking;

------------------------------------------------------------
-- DATA: Passengers - second passenger for ~40% of bookings (24,000)
------------------------------------------------------------

INSERT INTO passenger (booking_id, passenger_no, last_name, first_name, age)
SELECT
    booking_id,
    2,
    (ARRAY['Martinez','Lee','Hernandez','King','Wright',
           'Lopez','Hill','Scott','Green','Adams',
           'Baker','Hall','Allen','Young','Walker',
           'Perez','Turner','Torres','Phillips','Campbell'])[1 + booking_id % 20],
    (ARRAY['Sam','Pat','Morgan','Jordan','Taylor',
           'Riley','Casey','Drew','Skyler','Avery',
           'Blake','Emery','Harper','Parker','Sage',
           'Phoenix','River','Rowan','Eden','Kai'])[1 + booking_id % 20],
    5 + (booking_id % 40)
FROM booking
WHERE booking_id % 5 IN (0, 1);

------------------------------------------------------------
-- Cleanup temp table
------------------------------------------------------------

DROP TABLE numbered_airports;

------------------------------------------------------------
-- ORIGINAL SLOW FUNCTION (what the agent must optimize)
------------------------------------------------------------

CREATE OR REPLACE FUNCTION search_bookings_full(
    p_email text DEFAULT NULL,
    p_departure_airport text DEFAULT NULL,
    p_arrival_airport text DEFAULT NULL,
    p_departure_date date DEFAULT NULL,
    p_passenger_last_name text DEFAULT NULL,
    p_flight_status text DEFAULT NULL
) RETURNS TABLE(
    booking_id integer,
    booking_ref text,
    booking_name text,
    account_id integer,
    email text
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT b.booking_id, b.booking_ref, b.booking_name, b.account_id, b.email
    FROM booking b
    JOIN booking_leg bl ON bl.booking_id = b.booking_id
    JOIN flight f ON f.flight_id = bl.flight_id
    JOIN passenger p ON p.booking_id = b.booking_id
    WHERE (p_email IS NULL OR lower(b.email) LIKE lower(p_email) || '%')
      AND (p_departure_airport IS NULL OR f.departure_airport = p_departure_airport)
      AND (p_arrival_airport IS NULL OR f.arrival_airport = p_arrival_airport)
      AND (p_departure_date IS NULL OR f.scheduled_departure::date = p_departure_date)
      AND (p_passenger_last_name IS NULL OR lower(p.last_name) LIKE lower(p_passenger_last_name) || '%')
      AND (p_flight_status IS NULL OR f.status = p_flight_status);
END;
$$ LANGUAGE plpgsql;

------------------------------------------------------------
-- Set timezone persistently and update statistics
------------------------------------------------------------

ALTER SYSTEM SET timezone = 'UTC';
ANALYZE;
