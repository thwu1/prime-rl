A PostgreSQL 16 database `postgres_air` models an airline booking system with tables `airport`, `flight`, `booking`, `booking_leg`, `passenger`, and `account`. The database contains ~30K flights, ~60K bookings, and ~84K passengers across 30 airports and uses `en_US.UTF-8` collation. It is accessible as user `postgres` with trust authentication. PostgreSQL may need to be started.

The function `search_bookings_full(p_email text, p_departure_airport text, p_arrival_airport text, p_departure_date date, p_passenger_last_name text, p_flight_status text)` returns `TABLE(booking_id integer, booking_ref text, booking_name text, account_id integer, email text)`. All parameters default to NULL and act as optional filters — callers typically provide only one or two parameters per invocation.

This function has severe performance problems. Users report multi-second response times even on highly targeted searches (e.g., looking up bookings for a single specific email prefix, which should match only a handful of rows). Performance appears constant regardless of how selective the provided parameters are — a narrow search is as slow as an unfiltered one.

Investigate the root causes of the poor performance. Then create `/app/optimization.sql` that, when applied to the database, defines a function `search_bookings_optimized` with the identical signature and return type (returning columns `booking_id`, `booking_ref`, `booking_name`, `account_id`, `email`), along with supporting indexes, such that the following requirements are met:

**Function implementation:**

- The function must use dynamic SQL via PL/pgSQL's `EXECUTE` statement to build queries at runtime rather than relying on static SQL with OR-based nullability guards.
- SQL injection prevention must be implemented using `quote_literal()` or `format()` with the `%L` placeholder — do not use string concatenation of raw parameter values.
- The function must conditionally include JOIN clauses only when the parameters that target those joined tables are non-NULL. Specifically, use explicit `IS NOT NULL` checks on parameters to decide whether to join `booking_leg`/`flight` (needed for departure_airport, arrival_airport, departure_date, flight_status) and `passenger` (needed for passenger_last_name). When parameters are NULL, the corresponding tables must not be joined.

**Required indexes** (create all of these):

- An expression index on `booking` using `lower(email)` for case-insensitive email prefix searches.
- A composite index on `flight` covering at least `departure_airport` and `scheduled_departure` for route + date range queries.
- An index on `passenger(last_name)` (expression index on `lower(last_name)` preferred) for name prefix searches.
- An index on `booking_leg(booking_id)` (distinct from the primary key) for efficient joins from booking to booking_leg.
- An index on `booking_leg(flight_id)` for efficient joins from booking_leg to flight.

**Correctness and performance:**

- `search_bookings_optimized` must return the exact same result set as `search_bookings_full` for every parameter combination, including single-parameter searches (email only, departure airport only, flight status only, departure date only, passenger last name only) and multi-parameter combinations (email + passenger name, airport + status).
- Selective single-parameter queries must produce execution plans using index scans rather than sequential scans on the large tables.