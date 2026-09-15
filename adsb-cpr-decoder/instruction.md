A reference ADS-B Mode S decoder at `/app/decoder.py` reads messages from `/app/messages.txt` and writes decoded aircraft state to `/app/output.json`. The SQLite database `/app/aircraft.db` stores aircraft state vectors across multiple tables (some tables are operationally irrelevant noise). A compiled message integrity validator at `/app/msgcheck` provides independent checksum verification.

Create `/app/encoder.py` that reads aircraft states from the database, synthesizes Mode S messages, runs the decoder, validates with the integrity checker, and produces a validation report.

## Message format

Each encoded message in `/app/messages.txt` must use dump format: `*<28 hex characters>;` (one per line). All messages must be DF=17 (Downlink Format 17) extended squitter. There are 6 aircraft in the database, and the encoder must produce exactly 4 messages per aircraft (24 total): 1 identification message (TC 1-4), 2 position messages (one even-flag and one odd-flag CPR frame, TC 9-18), and 1 velocity message (TC 19).

## Error injection

The database contains an `error_injection` table specifying single-bit errors to inject into specific messages (identified by ICAO and message type). After constructing the CRC-valid message, flip the specified bit. These corrupted messages must remain single-bit correctable by the decoder's CRC-24 error correction. The database contains 2 error injection entries.

## Integrity validator

`/app/msgcheck` accepts a messages file as argument. It supports `-v` (verbose per-message details), `-j` (JSON output), and `-h` (help). When run with `-j -v`, it outputs JSON with fields: `total_messages`, `crc_valid`, `crc_corrected`, `crc_invalid`, `df17_messages`, and a `messages` array where each entry has `hex`, `crc_status`, `df`, and `tc`. For a correct encoding: `total_messages` = 24, `crc_valid` = 22, `crc_corrected` = 2, `crc_invalid` = 0, `df17_messages` = 24, with type code distribution of 6 identification + 12 position + 6 velocity messages.

## Decoder output

After running the decoder, `/app/output.json` must contain:

```json
{
  "aircraft": {
    "<ICAO>": {
      "callsign": "<string>",
      "position": {"lat": "<float>", "lon": "<float>"},
      "altitude": "<int>",
      "velocity": {
        "ground_speed": "<float>",
        "heading": "<float>",
        "vertical_rate": "<int>"
      }
    }
  },
  "statistics": {
    "total_messages": 24,
    "valid_messages": 22,
    "corrected_messages": 2,
    "unique_aircraft": 6
  }
}
```

All 6 aircraft (ICAOs: A1B2C3, D4E5F6, 789ABC, 1A2B3C, FE9876, C0FFEE) must appear with decoded callsigns, positions, altitudes, and velocities matching the database values within quantization tolerances: callsign exact match, altitude exact match, position error < 0.05 degrees, heading error < 1.5 degrees, ground speed error < 2.0 knots, vertical rate error < 64 ft/min. The position test cases include southern hemisphere, near-equator, near-antimeridian, and high-latitude coordinates.

## Validation report

The encoder must produce `/app/validation.json`:

```json
{
  "round_trip_results": {
    "<ICAO>": {
      "callsign_match": "<bool>",
      "position_error_deg": "<float>",
      "altitude_match": "<bool>",
      "velocity_error_kt": "<float>",
      "heading_error_deg": "<float>"
    }
  },
  "summary": {
    "total_aircraft": 6,
    "total_messages": 24,
    "successful_round_trips": 6,
    "error_injected_messages": 2,
    "error_corrected_messages": 2
  }
}
```

A round trip succeeds when callsign matches exactly, position error < 0.05 degrees, altitude matches exactly, and heading error < 1.0 degrees. All 6 aircraft must achieve successful round trips.