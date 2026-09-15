A spatial autocorrelation analysis pipeline is deployed at `/app/pipeline.py`. It processes sensor observations (`/app/data/observations.csv`) and administrative zone boundaries (`/app/data/zones.geojson`) to compute zone-level spatial statistics. The pipeline runs without crashing but produces incorrect analytical results across multiple output files.

There are issues spanning data quality and algorithmic correctness. Investigate the input data and pipeline implementation, identify and fix all problems, and regenerate correct output to `/app/output/`:

- `zone_values.json` -- `{"zone_id": mean_value, ...}` for all 36 zones
- `spatial_weights.json` -- `{"zone_id": ["neighbor_id", ...], ...}` queen contiguity adjacency
- `global_autocorrelation.json` -- Global Moran's I test: keys `morans_i`, `expected_i`, `variance`, `z_score`, `p_value`
- `local_clusters.geojson` -- GeoJSON FeatureCollection; properties: `zone_id`, `value`, `local_morans_i`, `z_score`, `p_value`, `cluster_type` (HH/HL/LH/LL/NS)
- `hotspot_analysis.geojson` -- GeoJSON FeatureCollection; properties: `zone_id`, `value`, `gi_star`, `z_score`, `p_value`, `classification` (Hot Spot/Cold Spot/Not Significant)
- `summary.json` -- keys: `n_zones`, `n_observations`, `mean_value`, `global_morans_i`, `global_p_value`, `n_hot_spots`, `n_cold_spots`, `n_high_high`, `n_low_low`