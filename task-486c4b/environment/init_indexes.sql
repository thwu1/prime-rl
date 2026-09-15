-- FK indexes for join support
CREATE INDEX idx_bl_booking_id ON booking_leg(booking_id);
CREATE INDEX idx_bl_flight_id ON booking_leg(flight_id);
CREATE INDEX idx_passenger_booking_id ON passenger(booking_id);
CREATE INDEX idx_cf_passenger_id ON custom_field(passenger_id);

-- Column indexes on search-relevant tables (pre-existing)
CREATE INDEX idx_booking_email ON booking(email);
CREATE INDEX idx_cf_name ON custom_field(custom_field_name);
