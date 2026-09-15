The `postgres_air` database supports an airline booking search through the PL/pgSQL function `search_bookings_full` (source at `/app/slow_function.sql`). The function accepts six optional parameters (`p_email`, `p_dep_airport`, `p_arr_airport`, `p_dep_date`, `p_passenger_last_name`, `p_passport_country`) and queries across multiple tables (~25K bookings, ~10K flights, ~35K passengers). Customer support reports that every search is unacceptably slow regardless of which parameters are provided or how selective they are.

Diagnose the root causes of the performance problems and create a drop-in replacement named `search_bookings_optimized` with the same six-parameter signature and identical return type.

## Optimized function requirements

- Must use **dynamic SQL** via `EXECUTE` to build queries at runtime, so that only relevant filters and joins are included.
- Must use `quote_literal()`, `format()`, or `quote_ident()` to construct SQL safely (no string concatenation of user input).
- Must raise an exception when invoked with all six parameters NULL.
- Must return identical result sets to `search_bookings_full` for every valid parameter combination.

## Required indexes

Create indexes that eliminate sequential scans on filtered tables. At minimum:

- An expression index on `booking(lower(email))` to support case-insensitive email prefix searches.
- An index on `flight(departure_airport)` to support departure airport lookups.
- An index on `passenger` covering `last_name` to support passenger name searches.
- A composite index on `custom_field(custom_field_name, custom_field_value)` to support EAV-pattern passport country lookups.

## Query plan quality

After applying indexes and updating statistics, query plans must use index-based access (not sequential scans) on `booking` for email searches, on `flight` for departure airport searches, and on `custom_field` for passport country searches.

## Output files

Write index definitions to `/app/indexes.sql` and the function to `/app/optimized_search.sql`. Apply both to the running database and run `ANALYZE` to update planner statistics.

PostgreSQL 16 is installed but not running. Database `postgres_air`, user `postgres`, trust authentication.