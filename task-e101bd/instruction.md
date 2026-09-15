An aircraft surveillance ground station recorded transponder data to `/app/station_capture.bin` using a proprietary binary logging format. No format documentation exists. The station also maintains an aircraft registry database at `/app/registry.db` (SQLite).

Analyze the binary capture file, extract the embedded transponder messages, decode flight parameters for each aircraft, and cross-reference with the registry database. Produce a JSON tracking report at `/app/aircraft_report.json`.

The report must be a JSON object keyed by each aircraft's 24-bit hex identifier (uppercase). Only include aircraft whose messages pass the protocol's built-in integrity check. Each entry must contain:

```json
{
  "callsign": "...",
  "lat": ...,
  "lon": ...,
  "altitude_ft": ...,
  "ground_speed_kts": ...,
  "heading_deg": ...,
  "vertical_rate_fpm": ...,
  "num_valid_messages": ...,
  "registration": "...",
  "operator": "..."
}
```

Position fields (`lat`, `lon`) should be `null` if insufficient data is available for unambiguous decoding. Other flight fields should be `null` if the corresponding message type was not received. Registry fields (`registration`, `operator`) should be `null` if the aircraft is not found in the database.