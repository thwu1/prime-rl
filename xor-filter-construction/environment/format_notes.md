# SensorStream Binary Format - Engineering Notes
Last updated: 2023-12-15

## Overview
Binary container for time-series sensor data from an industrial monitoring deployment.
Approximately 30 days of continuous recording from ~100 sensors, starting January 2024.

## File Layout
- 32-byte file header
- N x 32-byte data records (N is stored in the header)

## Header
- Starts with magic bytes: `\x89SEN` (4 bytes)
- Contains the total record count as an unsigned 32-bit integer
- Contains deployment time range (start and end timestamps)
- Contains sensor count
- Header has its own integrity check (4 bytes, at the end of the header)

## Data Records
- Each record is exactly 32 bytes
- Byte 0 encodes the record type:
  - Type 0: Temperature (degrees Celsius)
  - Type 1: Atmospheric Pressure (hPa)
  - Type 2: Relative Humidity (%)
- Record contains a 16-bit unsigned sensor identifier
- Record contains a 64-bit timestamp (epoch-based)
- Record contains IEEE 754 floating-point measurement value(s)
- An integrity check field exists near the end of each record
- Final 2 bytes of each record are padding

## Engineering Notes
- Format was designed for a heterogeneous sensor network (mixed ARM and x86 nodes),
  which influenced some encoding choices
- Approximately 2% of records are diagnostic/calibration data that should be excluded
  from production analytics
- Each record carries both a raw measurement and a derived/converted value

## TODO (never completed)
- [ ] Document the quality metadata encoding in the type byte
- [ ] Write full byte-level specification for onboarding
- [ ] Verify and document the checksum algorithm used in records
