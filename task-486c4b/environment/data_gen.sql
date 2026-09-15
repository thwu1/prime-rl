-- Deterministic data generation for postgres_air

-- 20 airports
INSERT INTO airport (airport_code, airport_name, city, iso_country) VALUES
('ATL', 'Hartsfield-Jackson Atlanta International Airport', 'Atlanta', 'US'),
('BOS', 'Boston Logan International Airport', 'Boston', 'US'),
('CDG', 'Charles de Gaulle Airport', 'Paris', 'FR'),
('DEL', 'Indira Gandhi International Airport', 'Delhi', 'IN'),
('DEN', 'Denver International Airport', 'Denver', 'US'),
('DFW', 'Dallas/Fort Worth International Airport', 'Dallas', 'US'),
('FRA', 'Frankfurt Airport', 'Frankfurt', 'DE'),
('GRU', 'Guarulhos International Airport', 'Sao Paulo', 'BR'),
('JFK', 'John F. Kennedy International Airport', 'New York', 'US'),
('LAX', 'Los Angeles International Airport', 'Los Angeles', 'US'),
('LHR', 'London Heathrow Airport', 'London', 'GB'),
('MEX', 'Mexico City International Airport', 'Mexico City', 'MX'),
('MIA', 'Miami International Airport', 'Miami', 'US'),
('NRT', 'Narita International Airport', 'Tokyo', 'JP'),
('ORD', 'O''Hare International Airport', 'Chicago', 'US'),
('SEA', 'Seattle-Tacoma International Airport', 'Seattle', 'US'),
('SFO', 'San Francisco International Airport', 'San Francisco', 'US'),
('SYD', 'Sydney Kingsford Smith Airport', 'Sydney', 'AU'),
('YVR', 'Vancouver International Airport', 'Vancouver', 'CA'),
('YYZ', 'Toronto Pearson International Airport', 'Toronto', 'CA');

-- 10,000 flights across 90 days starting 2020-06-01
INSERT INTO flight (flight_no, departure_airport, arrival_airport,
                    scheduled_departure, scheduled_arrival, status)
SELECT
    'PA' || lpad(s::text, 5, '0'),
    d.airport_code,
    a.airport_code,
    '2020-06-01 00:00:00+00'::timestamptz
        + (s % 90) * interval '1 day'
        + (s % 24) * interval '1 hour',
    '2020-06-01 00:00:00+00'::timestamptz
        + (s % 90) * interval '1 day'
        + ((s % 24) + 2 + (s % 4)) * interval '1 hour',
    CASE WHEN s % 20 = 0 THEN 'Canceled' ELSE 'On schedule' END
FROM generate_series(1, 10000) s
JOIN (SELECT airport_code, row_number() OVER (ORDER BY airport_code) - 1 AS idx
      FROM airport) d ON d.idx = s % 20
JOIN (SELECT airport_code, row_number() OVER (ORDER BY airport_code) - 1 AS idx
      FROM airport) a ON a.idx = (s * 7 + 3) % 20;

-- 25,000 bookings
WITH name_data AS (
    SELECT
        ARRAY['James','Mary','Robert','Patricia','John',
              'Jennifer','Michael','Linda','David','Elizabeth',
              'William','Barbara','Richard','Susan','Joseph',
              'Jessica','Thomas','Sarah','Charles','Karen'] AS fn,
        ARRAY['Smith','Johnson','Williams','Brown','Jones',
              'Garcia','Miller','Davis','Rodriguez','Martinez',
              'Hernandez','Lopez','Gonzalez','Wilson','Anderson',
              'Thomas','Taylor','Moore','Jackson','Martin'] AS ln,
        ARRAY['@example.com','@mail.com','@test.org',
              '@company.net','@domain.io'] AS dm
)
INSERT INTO booking (booking_ref, booking_name, email, account_id)
SELECT
    'BK' || lpad(s::text, 8, '0'),
    nd.fn[1 + s % 20] || ' ' || nd.ln[1 + (s * 3) % 20],
    lower(nd.fn[1 + s % 20]) || '.' || lower(nd.ln[1 + (s * 3) % 20])
        || (s % 500)::text || nd.dm[1 + s % 5],
    1 + s % 10000
FROM generate_series(1, 25000) s, name_data nd;

-- Booking legs: first leg for all 25K bookings
INSERT INTO booking_leg (booking_id, flight_id, leg_num, is_returning)
SELECT s, 1 + (s * 3) % 10000, 1, false
FROM generate_series(1, 25000) s;

-- Return legs for 60% of bookings
INSERT INTO booking_leg (booking_id, flight_id, leg_num, is_returning)
SELECT s, 1 + (s * 7 + 5) % 10000, 2, true
FROM generate_series(1, 15000) s;

-- Passengers: one per booking
WITH name_data AS (
    SELECT
        ARRAY['James','Mary','Robert','Patricia','John',
              'Jennifer','Michael','Linda','David','Elizabeth',
              'William','Barbara','Richard','Susan','Joseph',
              'Jessica','Thomas','Sarah','Charles','Karen'] AS fn,
        ARRAY['Smith','Johnson','Williams','Brown','Jones',
              'Garcia','Miller','Davis','Rodriguez','Martinez',
              'Hernandez','Lopez','Gonzalez','Wilson','Anderson',
              'Thomas','Taylor','Moore','Jackson','Martin'] AS ln
)
INSERT INTO passenger (booking_id, passenger_no, last_name, first_name, age)
SELECT s, 1, nd.ln[1 + (s * 11) % 20], nd.fn[1 + (s * 13) % 20], 18 + s % 60
FROM generate_series(1, 25000) s, name_data nd;

-- Second passenger for 40% of bookings
WITH name_data AS (
    SELECT
        ARRAY['James','Mary','Robert','Patricia','John',
              'Jennifer','Michael','Linda','David','Elizabeth',
              'William','Barbara','Richard','Susan','Joseph',
              'Jessica','Thomas','Sarah','Charles','Karen'] AS fn,
        ARRAY['Smith','Johnson','Williams','Brown','Jones',
              'Garcia','Miller','Davis','Rodriguez','Martinez',
              'Hernandez','Lopez','Gonzalez','Wilson','Anderson',
              'Thomas','Taylor','Moore','Jackson','Martin'] AS ln
)
INSERT INTO passenger (booking_id, passenger_no, last_name, first_name, age)
SELECT s, 2, nd.ln[1 + (s * 17) % 20], nd.fn[1 + (s * 19) % 20], 18 + (s * 7) % 60
FROM generate_series(1, 10000) s, name_data nd;

-- Custom fields: 3 per passenger (passport_num, passport_exp_date, passport_country)
INSERT INTO custom_field (passenger_id, custom_field_name, custom_field_value)
SELECT passenger_id, 'passport_num',
       lpad(((passenger_id * 12345) % 1000000000)::text, 10, '0')
FROM passenger;

INSERT INTO custom_field (passenger_id, custom_field_name, custom_field_value)
SELECT passenger_id, 'passport_exp_date',
       ('2023-01-01'::date + (passenger_id % 1825) * interval '1 day')::date::text
FROM passenger;

INSERT INTO custom_field (passenger_id, custom_field_name, custom_field_value)
SELECT passenger_id, 'passport_country',
       (ARRAY['US','CA','GB','DE','FR','JP','AU','BR','MX','IN'])[1 + passenger_id % 10]
FROM passenger;
