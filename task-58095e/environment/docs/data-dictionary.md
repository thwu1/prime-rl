# Hazard Database Data Dictionary

The seismic source model is stored in `/app/hazard.db` (SQLite). Below is a description
of each table.

## sources

Primary catalog of seismic sources.

| Column | Description |
|--------|-------------|
| source_id | Unique integer identifier |
| name | Human-readable source name |
| source_type | Either `fault` or `point` |
| description | Optional text description |

## fault_traces

Ordered geographic coordinates defining each fault's surface trace. Multiple rows
per fault, ordered by `point_order`.

| Column | Description |
|--------|-------------|
| source_id | References `sources.source_id` |
| point_order | 0-indexed sequence number |
| longitude | WGS84 degrees |
| latitude | WGS84 degrees |

## fault_properties

Geometric parameters for fault sources.

| Column | Description |
|--------|-------------|
| source_id | References `sources.source_id` |
| dip_degrees | Fault dip angle from horizontal |
| rake_degrees | Slip direction |
| upper_depth_km | Depth to upper edge of rupture |
| lower_depth_km | Depth to lower edge of rupture |

## point_locations

Geographic location and depth for point sources.

| Column | Description |
|--------|-------------|
| source_id | References `sources.source_id` |
| longitude | WGS84 degrees |
| latitude | WGS84 degrees |
| depth_km | Source depth |

## mfd_parameters

Magnitude-frequency distribution parameters. Column usage depends on `mfd_type`.

| Column | Description |
|--------|-------------|
| source_id | References `sources.source_id` |
| mfd_type | `GR` (Gutenberg-Richter) or `SINGLE` |
| a_value | GR a-value (NULL for SINGLE) |
| b_value | GR b-value (NULL for SINGLE) |
| m_min | GR minimum magnitude (NULL for SINGLE) |
| m_max | GR maximum magnitude (NULL for SINGLE) |
| delta_m | GR magnitude bin width (NULL for SINGLE) |
| magnitude | SINGLE fixed magnitude (NULL for GR) |
| rate | SINGLE annual rate (NULL for GR) |

## gmm_tree

Ground motion model logic tree entries.

| Column | Description |
|--------|-------------|
| gmm_id | Unique integer identifier |
| name | Model name |
| weight | Logic tree weight (weights sum to 1.0) |

## gmm_coefficients

GMM coefficients stored as name-value pairs (one row per coefficient per model).

| Column | Description |
|--------|-------------|
| gmm_id | References `gmm_tree.gmm_id` |
| coefficient_name | Coefficient identifier (e.g. `c0`, `sigma`) |
| coefficient_value | Numeric value |

## model_metadata

Model-level configuration and metadata stored as key-value pairs.

| Column | Description |
|--------|-------------|
| key | Parameter name |
| value | Parameter value (text; cast as needed) |

Notable metadata keys include `max_distance_km` (distance cutoff), `gmm_formula`
(GMM functional form), and `coordinate_convention`.
