A multi-calendar date conversion engine at `/app/` converts dates between proleptic Gregorian,
proleptic Julian, and tabular Islamic calendars, computes ISO 8601 week dates and weekdays,
and performs timezone-aware UTC offset calculations using DST rules from a data file.
The project uses CMake with separate library and executable targets across multiple source files.

Fix the build system, all calendar algorithm bugs, and timezone conversion errors,
and implement the missing ISO 8601 week date feature so the engine passes all tests.

Commands (one query per stdin line, one result per stdout line):

- `CONVERT <src> <y> <m> <d> <dst>` outputs `<y> <m> <d>` in the destination calendar.
- `WEEKDAY <cal> <y> <m> <d>` outputs `<wd>` (0=Sun, 1=Mon, ..., 6=Sat).
- `ISO_WEEK <y> <m> <d>` outputs `<iso_year> <iso_week> <iso_weekday>` (weekday: 1=Mon..7=Sun).
- `FROM_ISO_WEEK <iso_year> <iso_week> <iso_weekday>` outputs `<y> <m> <d>`.
- `TZ_OFFSET <zone> <y> <m> <d> <h> <min>` outputs `<offset_minutes>` (signed UTC offset for that local time).
- `TO_UTC <zone> <y> <m> <d> <h> <min>` outputs `<y> <m> <d> <h> <min>` (UTC equivalent, handling day rollover).

Calendar identifiers: `gregorian`, `julian`, `islamic`. All share serial day 0 = Gregorian 1970-01-01 (Thursday, weekday 4).

Requirements:

- Build: `cd /app && mkdir -p build && cd build && cmake .. && cmake --build .` must produce `/app/build/calendar_engine`.
- Round-trip conversions within any single calendar are identity for all valid dates.
- Cross-calendar conversions are exact across the full `int64_t` serial day range.
- Weekdays correct for all serial days including negative values.
- ISO 8601: week 1 contains January 4; weeks start Monday; an ISO year has 52 or 53 weeks.
- Timezone rules loaded from `/app/data/tz_rules.csv`. DST transitions use Nth-weekday-of-month rules (fields: zone, std_offset, dst_offset, start month/dow/week/hour, end month/dow/week/hour). DST is active starting at the exact transition hour. Southern-hemisphere zones where `dst_start_month > dst_end_month` must be handled.
- `TO_UTC` subtracts the applicable offset from local time, rolling the date forward or backward as needed.
