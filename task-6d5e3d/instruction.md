A previous developer attempted to deploy a meteorological station data API at `/app/` using pygeoapi with a custom SQLite provider plugin. The deployment was never successfully completed — the server is not running and the implementation contains multiple defects in both the provider code and the pygeoapi configuration.

The environment contains:

- pygeoapi (installed)
- SQLite database at `/app/data/stations.db` with a `stations` table containing 25 global meteorological sensor stations
- Custom provider plugin at `/app/plugins/station_provider.py`
- pygeoapi configuration at `/app/config.yml`

Diagnose and fix all issues so that the service runs as a fully conformant OGC API - Features endpoint at collection `stations` on `0.0.0.0:5000`. The working service must correctly support:

- GeoJSON Feature/FeatureCollection output with Point geometries following RFC 7946 coordinate ordering
- Pagination via offset/limit with `numberMatched` and `numberReturned` counts that accurately reflect any active filters
- A count-only mode (`resulttype=hits`) returning the matched count without feature bodies
- Bounding box spatial filtering via the `bbox` parameter
- Property-based equality filtering on text and numeric columns
- Temporal filtering via the `datetime` parameter against observation timestamps, supporting ISO 8601 instants and interval syntax including open-ended ranges
- Single-feature retrieval by ID, with proper HTTP error status for nonexistent features
- CRS negotiation: the collection must advertise CRS84, EPSG:4326, and EPSG:3857, and respond correctly to CRS-parameterized requests
- Transactional create, update, and delete operations through the API

The server must be running and responsive when evaluation begins.