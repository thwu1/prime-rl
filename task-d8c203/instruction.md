A PostgreSQL 16 instance hosts the `postgres_air` database (schema `postgres_air`). Start it with `pg_ctlcluster 16 main start` and connect as user `postgres` (trust auth configured). Core tables: `airport`, `flight`, `booking`, `booking_leg`, `passenger`.

The function `postgres_air.select_booking_advanced(p_email, p_last_name, p_departure_airport, p_arrival_airport, p_departure_date, p_booking_ref)` is a dynamic SQL booking search API. It accepts optional parameters and returns matching bookings with flight and passenger details via output columns `out_booking_id`, `out_booking_ref`, `out_booking_name`, `out_email`, `out_departure_airport`, `out_arrival_airport`, `out_scheduled_departure`, `out_passenger_last_name`.

Production has escalated multiple interacting defects against this function. Investigate the function's PL/pgSQL source (available in `pg_catalog`), the schema, and the index infrastructure on the `booking` table. Diagnose every root cause and remediate all issues against the live database. The function signature and return type must be preserved.

**Reported production incidents:**

1. **SEV-1 — Security**: The security team's penetration test flagged the function as exploitable via at least one text parameter. Injection payloads must return 0 rows without errors. Names containing apostrophes (e.g., O'Brien) must not cause SQL errors.

2. **SEV-2 — Inflated result counts**: When `p_email` and `p_departure_date` are combined, the function's result count does not match a direct query computing `count(DISTINCT booking_id)` with AND-intersection semantics against the underlying tables. The function must always return the intersection of all supplied criteria.

3. **SEV-3 — Case mismatch**: Searching `p_email := 'john.smith.upper'` returns 0 rows even though a booking with email `JOHN.SMITH.UPPER@gmail.com` exists. Email searches must match regardless of stored case.

4. **SEV-3 — Email query performance**: Email prefix searches via the function trigger sequential scans despite the booking table having email-related indexes. Investigate every email-related index on the booking table — determine why none of them support the query pattern the function actually needs. After remediation, `EXPLAIN` for an email prefix search on the booking table must show an index scan, not a sequential scan.

5. **SEV-3 — Excessive resource usage**: An email-only search currently returns non-NULL values for flight and passenger columns even though those tables are irrelevant to the query. When only a subset of parameters is provided, output columns from unneeded tables must be NULL, and the underlying query must not join those tables unnecessarily.

6. **Departure airport correctness**: Filtering by `p_departure_airport := 'JFK'` must return a booking count matching a direct reference query against the underlying tables (`SELECT count(DISTINCT b.booking_id) FROM booking b JOIN booking_leg bl ... JOIN flight f ... WHERE f.departure_airport = 'JFK'`).

A representative production workload is at `/app/workload.sql`.