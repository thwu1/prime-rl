-- Schema for postgres_air database
-- Airline booking system with airports, flights, bookings, passengers, and custom fields

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

CREATE TABLE booking (
    booking_id serial PRIMARY KEY,
    booking_ref text NOT NULL,
    booking_name text NOT NULL,
    email text,
    account_id int,
    update_ts timestamptz DEFAULT now()
);

CREATE TABLE booking_leg (
    booking_leg_id serial PRIMARY KEY,
    booking_id int NOT NULL REFERENCES booking(booking_id),
    flight_id int NOT NULL REFERENCES flight(flight_id),
    leg_num int NOT NULL DEFAULT 1,
    is_returning boolean DEFAULT false,
    update_ts timestamptz DEFAULT now()
);

CREATE TABLE passenger (
    passenger_id serial PRIMARY KEY,
    booking_id int NOT NULL REFERENCES booking(booking_id),
    passenger_no int NOT NULL DEFAULT 1,
    last_name text NOT NULL,
    first_name text NOT NULL,
    age int
);

CREATE TABLE custom_field (
    custom_field_id serial PRIMARY KEY,
    passenger_id int NOT NULL REFERENCES passenger(passenger_id),
    custom_field_name text NOT NULL,
    custom_field_value text
);
