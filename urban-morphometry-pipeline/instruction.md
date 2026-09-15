Using the `momepy` library (pre-installed) and its bundled bubenec dataset, compute a comprehensive multi-scale urban morphometric profile of the Bubenec neighborhood in Prague.

Load data via `momepy.datasets.get_path("bubenec")` with layers `buildings` (144 building polygons), `streets` (35 street lines), and `tessellation` (144 Voronoi cells). Synthesize building heights as `numpy.linspace(10.0, 30.0, 144)`.

Write results to `/app/morphometric_profile.json` with this exact structure:

```
{
  "counts": {
    "buildings": <int>,
    "streets": <int>,
    "tessellation_cells": <int>
  },
  "shape": {
    "fractal_dimension_mean": <float>,
    "circular_compactness_mean": <float>,
    "square_compactness_mean": <float>,
    "convexity_mean": <float>,
    "rectangularity_mean": <float>,
    "elongation_mean": <float>,
    "equivalent_rectangular_index_mean": <float>,
    "corners_sum": <int>,
    "squareness_mean": <float>
  },
  "dimension": {
    "courtyard_area_sum": <float>,
    "form_factor_mean": <float>
  },
  "distribution": {
    "orientation_buildings_mean": <float>,
    "orientation_streets_mean": <float>,
    "shared_walls_mean": <float>,
    "alignment_mean": <float>,
    "neighbor_distance_mean": <float>,
    "building_adjacency_mean": <float>,
    "street_alignment_mean": <float>,
    "linearity_mean": <float>
  },
  "diversity": {
    "shannon_mean": <float>,
    "simpson_mean": <float>,
    "gini_mean": <float>,
    "theil_mean": <float>
  },
  "coins": {
    "stroke_count": <int>,
    "n_segments": [<int>, ...]
  }
}
```

**Graph configuration** (critical for correct results):
- **Distribution** (`alignment`, `neighbor_distance`): KNN graph with k=5 built from building centroids
- **Building adjacency** requires two graphs: contiguity graph of building polygons with default parameters (contiguity structure) and KNN k=5 from building centroids (neighborhood scope)
- **Diversity** (`shannon`, `simpson`, `gini`, `theil`): contiguity of tessellation cells (default parameters), expanded to third-order (including lower orders), with self-weight assigned. Compute over tessellation cell areas.
- **Street alignment**: identify nearest street for each building, then compute deviation between building and street orientations
- **COINS**: default parameters; report stroke count and per-stroke segment counts from `stroke_gdf()`

All shape metrics use default parameters on building polygons. Suffix `_mean` denotes arithmetic mean across features; `_sum` denotes sum.