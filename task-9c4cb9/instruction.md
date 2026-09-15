Three ADS-B ground stations captured overlapping Mode S extended squitter traffic during the same time window. Station message dumps (`alpha.hex`, `bravo.hex`, `charlie.hex`) and station metadata (`stations.json`) are in `/app/stations/`. Protocol reference is at `/app/docs/mode_s_reference.txt`. A message CRC validation utility is at `/app/tools/msg_check`. The required database schema is at `/app/docs/db_schema.sql`.

Create `/app/pipeline.py` — a track fusion pipeline invocable as:

    python3 /app/pipeline.py /app/stations /app/tracks.db /app/report.json

The pipeline ingests hex-encoded DF17 messages from all station `*.hex` files, implements CRC-24 syndrome-based single-bit error correction, decodes identification (TC 1-4), airborne position (TC 9-18) via CPR global decoding, and airborne velocity (TC 19, subtype 1). All raw messages must be recorded in a SQLite database conforming to `/app/docs/db_schema.sql`, including station provenance and CRC status. Cross-station duplicate messages (identical raw hex) must be tracked.

One aircraft in the capture data has been spoofed — its consecutive decoded positions imply physically impossible displacement. The pipeline must identify this aircraft through kinematic analysis of inter-position great-circle distances.

Output `/app/report.json`:

```json
{
  "aircraft": {
    "<ICAO_HEX>": {
      "callsign": "<string or null>",
      "positions": [{"lat": <float>, "lon": <float>, "alt": <int>}],
      "velocities": [{"gs": <float>, "hdg": <float>, "vr": <int>}],
      "stations": ["<station_id>", ...],
      "anomaly": <bool>
    }
  },
  "stats": {
    "total_messages": <int>,
    "unique_messages": <int>,
    "corrected_messages": <int>,
    "invalid_messages": <int>,
    "aircraft_count": <int>,
    "spoofed_icao": "<ICAO_HEX>"
  }
}
```

ICAO addresses are uppercase 6-character hex. Latitudes and longitudes are decimal degrees. Headings are degrees in [0, 360). `unique_messages` counts distinct raw hex strings across all stations. The `stations` list contains IDs of stations that received at least one valid or corrected message for that aircraft.