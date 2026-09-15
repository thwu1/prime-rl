-- Application workload samples from production query log
-- Run these against the live database to reproduce reported issues

-- Customer support: find bookings by email prefix
SELECT * FROM postgres_air.select_booking_advanced(p_email := 'john.smith0@g');

-- Customer support: find booking by passenger name
SELECT * FROM postgres_air.select_booking_advanced(p_last_name := 'Smith');

-- Travel agent: bookings for email and specific departure date
SELECT count(DISTINCT out_booking_id) FROM postgres_air.select_booking_advanced(
    p_email := 'john.smith', p_departure_date := '2024-06-15');

-- Operations: all bookings departing JFK
SELECT count(DISTINCT out_booking_id) FROM postgres_air.select_booking_advanced(
    p_departure_airport := 'JFK');

-- Quick lookup by booking reference
SELECT * FROM postgres_air.select_booking_advanced(p_booking_ref := 'C4CA42');
