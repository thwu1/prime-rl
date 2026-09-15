`/app/data/flare_catalog.csv` contains ~27,000 GOES solar flare events (2010-2024) with X-ray classification strings, timestamps, NOAA active region numbers, and heliographic positions from multiple sources (numeric `lat_stony`/`lon_stony`, numeric `lat_ssw`/`lon_ssw`, and `location_ssw` strings like `N24E77`). The numeric coordinate columns contain a systematic data quality problem that must be discovered and corrected.

Produce the following files in `/app/output/`:

**`coordinate_audit.json`** — Keys: `total_events`, `events_with_any_coords`, `events_no_coords` (ints), `data_quality_issues` (list of strings describing discovered systematic problems).

**`corrected_catalog.csv`** — All events with columns: `event_starttime`, `fl_goescls`, `ar_noaanum`, `hgs_lat` (Stonyhurst latitude, degrees), `hgs_lon` (Stonyhurst longitude, west-positive), `hgc_lat`, `hgc_lon` (Carrington, [0,360)), `carrington_rotation` (integer), `coord_source`, `has_coords` (boolean). Stonyhurst-to-Carrington transforms must use each event's observation time.

**`rotation_profile.csv`** — Per Carrington rotation: `carrington_rotation`, `total_flares`, `a_class`, `b_class`, `c_class`, `m_class`, `x_class`, `total_goes_flux` (cumulative peak W/m²), `peak_activity_longitude` (center of 30° bin with most flares).

**`geoeffective_events.csv`** — M/X-class flares with valid coordinates, including corrected catalog columns plus `angular_distance_deg` (from disk center) and `geo_score` ([0,1], 1.0 at disk center, 0.0 at limb).

**`ar_summary.csv`** — Per active region (valid NOAA numbers only): `ar_noaanum`, `total_flares`, `c_class`, `m_class`, `x_class`, `total_goes_flux`, `mean_hgc_lon`, `first_seen`, `last_seen`.