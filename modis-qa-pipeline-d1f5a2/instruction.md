Build a Python CLI tool at `/app/satqa.py` that processes satellite remote sensing observations from multiple MODIS and Landsat products. The tool must dynamically query the USGS AppEEARS API (`https://appeears.earthdatacloud.nasa.gov/api`) to obtain all product-specific metadata needed to interpret the observations. No authentication is required.

**Invocation:**
```
python3 /app/satqa.py /app/input.jsonl /app/filter.json /app/output.jsonl
```

**Input** (`/app/input.jsonl`): One JSON object per line with fields `id`, `product`, `qa_layer`, `qa_value` (packed integer), and `measurements` (array of `{"layer", "raw"}` objects).

**Filter** (`/app/filter.json`): Keys are `"product/qa_layer"` strings mapping to objects of `{field_name: [acceptable_values]}`. An observation passes quality only if every field named in its applicable filter entry has a decoded value within the acceptable list. Fields not in the filter are unconstrained. If no filter entry exists for a product/layer combination, the observation passes.

**Output** (`/app/output.jsonl`): One JSON object per line containing:
- `id`, `product`: from input
- `qa_decode`: object mapping each decoded QA field name to `{"value": <int>, "description": <string>}`. Field names and descriptions must match the AppEEARS API exactly.
- `quality_passed`: boolean result of applying the filter
- `scaled_measurements`: array of `{"layer", "raw", "scaled", "units", "is_fill"}`. Use each layer's metadata from the API to transform raw values. When a raw value matches the layer's designated fill value, set `scaled` to `null` and `is_fill` to `true`.
- `computed_indices`: object. For MOD09GA.061 observations containing Red (b01), NIR (b02), and Blue (b03) surface reflectance bands, compute the Enhanced Vegetation Index. If any input band is fill, the index value must be `null`.

**Report** (`/app/report.json`): JSON object with:
- `total`: count of observations processed
- `by_product`: `{product: {"total", "passed", "failed"}}` tallying quality outcomes per product
- `fill_count`: total individual measurements flagged as fill across all observations
- `indices_computed`: `{index_name: count}` of non-null index computations

All QA bitmask field definitions, layer metadata, and product schemas must be obtained from the AppEEARS API at runtime. Do not hardcode product-specific structures. Cache API responses to avoid redundant network requests.
