A Python HTTP server at `/app/server.py` implements an OGC API - Features Part 1 endpoint serving geospatial feature data from `/app/data/`. It can be started via `/app/start.sh` (port 5000).

The server has multiple conformance violations against the OGC API - Features 1.0 specification (http://www.opengis.net/spec/ogcapi-features-1/1.0). A TEAM Engine conformance report from a prior test run is at `/app/conformance-report.xml` — however, this report was generated against an older revision of the server. The code has been modified since: some previously-reported violations may already be resolved, new violations may have been introduced, and some passing results in the report may be coincidental (e.g., a bbox test that only exercised global extent and never caught a coordinate-handling bug).

Conformance violations may exist at any layer — server logic, API response formatting, metadata computation, or the source GeoJSON data files themselves. The server must fully satisfy the Core and GeoJSON conformance classes:

- `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core`
- `http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson`

This encompasses landing page structure and link relations, conformance declaration, OpenAPI 3.0 API definition, collection metadata with correct spatial/temporal extents in CRS84, feature retrieval returning valid GeoJSON with accurate counts, spatial filtering via `bbox` in CRS84 axis order, temporal filtering via `datetime` including open-ended intervals, pagination that preserves active query filters, and proper error handling for invalid or unknown query parameters.

All GeoJSON geometry coordinates must conform to the GeoJSON specification (RFC 7946): positions are `[longitude, latitude]` in CRS84. Any source data that violates this convention is itself a conformance violation that must be corrected.

The fixed server must remain startable via `/app/start.sh` on port 5000.