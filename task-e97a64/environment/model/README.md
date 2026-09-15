# Southern California Multi-Period Seismic Hazard Model

## Data Files

| File | Format | Description |
|------|--------|-------------|
| `sources.xml` | XML (namespaced) | Earthquake source definitions (point and fault types) |
| `gmm.db` | SQLite | Period-dependent ground motion model with logic tree branches |
| `sites.geojson` | GeoJSON | Target sites with Vs30 and basin depth (z1.0) |
| `config.toml` | TOML | Multi-period calculation configuration |

## Database Schema (gmm.db)

- `metadata` — key-value pairs: GMM functional form, distance metric, reference parameters
- `periods(id, imt, period_sec)` — intensity measure types and their spectral periods
- `branches(id, period_id, weight, sigma)` — per-period logic tree branches with aleatory sigma
- `coefficients(branch_id, period_id, name, value)` — per-branch, per-period named coefficients

Query `metadata` for the GMM formula and reference parameters. Coefficients are indexed by both `branch_id` and `period_id`.

## Source Model

Sources use XML namespaces:
- `urn:nshmp:sources:1.0` — top-level source elements and point locations
- `urn:nshmp:mfd:1.0` — magnitude-frequency distributions with epistemic branching
- `urn:nshmp:fault:1.0` — fault geometry (trace, dip, depth range) and rupture scaling

Point sources specify epicentral location and hypocentral depth. Fault sources specify a surface trace, dip angle, upper/lower depth range, and magnitude-dependent rupture length scaling.

## Conventions

- Coordinates: WGS84 decimal degrees (lon/lat)
- Distances in km; spectral accelerations in g
- Fault traces follow the right-hand rule: walking from first to last vertex, the fault dips to the right
- Minimum distance clamp: 0.1 km
