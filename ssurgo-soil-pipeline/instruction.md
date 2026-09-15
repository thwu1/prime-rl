Build `/app/soil_report.py`, a Python CLI that queries the USDA Soil Data Access (SDA) service for SSURGO soil data and produces a structured JSON assessment report.

**CLI:** `python3 /app/soil_report.py --mukeys <comma-separated> [--depth-top N] [--depth-bottom N] --output <path>`

Defaults: `--depth-top 0`, `--depth-bottom 100` (centimeters). Exit 0 on success. Handle transient network failures gracefully.

**Output JSON** -- object with keys:

- `query_params`: `{mukeys: [str], depth_top_cm: int, depth_bottom_cm: int}`
- `mapunits`: object keyed by mukey string. Each:
  - `muname` (str), `mukind` (str)
  - `components`: object keyed by cokey string. Each:
    - `compname` (str), `comppct_r` (int), `hydgrp` (str|null), `drainagecl` (str|null), `taxsubgrp` (str|null)
    - `restriction_depth_cm`: shallowest restrictive layer depth in cm (float|null)
    - `horizons`: list sorted ascending by top depth. Each: `{hzdept_r, hzdepb_r, sandtotal_r, silttotal_r, claytotal_r, texture_class, awc_r, ksat_r, dbthirdbar_r}` -- depths int|null, other numerics float|null
    - `depth_weighted`: `{awc, ksat, dbthirdbar, aws_mm}` -- all float|null
  - `aggregated`: `{wtd_avg_awc, wtd_avg_ksat, wtd_avg_bd, wtd_avg_aws_mm, dominant_hydgrp, dominant_drainagecl}`
  - `interpretations`: keyed by `"ENG - Septic Tank Absorption Fields"`. Contains `components` (keyed by cokey, each `{rating_class: str, rating_value: float|null}`), `dominant_rating_class` (str|null), `weighted_rating_value` (float|null)

**Semantic requirements:**

- `texture_class`: standard USDA soil texture classification from particle-size fractions. Null when any fraction is null.
- Depth-weighted values reflect the effective depth range `[depth_top, depth_bottom]` narrowed by the shallowest restrictive layer. Null if no valid data exists within the effective range.
- `aws_mm`: total available water storage in millimeters across the effective depth range (cumulative, not a per-unit average).
- Continuous mapunit aggregations: component-percentage-weighted averages (non-null components only). Categorical: dominant condition -- greatest total component percentage; alphabetic tiebreak.
- Interpretation: use master-level records only. Dominant class and weighted value exclude "Not rated" components (case-insensitive).
- Components with no horizon data: empty horizons list, null depth-weighted values.
