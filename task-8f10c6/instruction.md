Build a Python script at `/app/pipeline.py` that processes satellite imagery and analysis zone data to produce spectral index rasters and per-zone statistics.

**Input data** in `/app/data/`:
- `multiband.tif` — 6-band satellite raster in EPSG:32633 (bands 1–6: Coastal, Blue, Green, Red, RedEdge, NIR)
- `zones.geojson` — 5 analysis zone polygons in EPSG:4326
- `analysis_config.json` — Configuration specifying spectral index formulas as band-math expressions using variables `b1`–`b6`, COG creation parameters, output nodata value, valid value ranges, and required zonal statistics

**Required outputs** in `/app/output/`:
- `indices/<INDEX_NAME>.tif` — One Cloud Optimized GeoTIFF per spectral index, internally tiled with overviews, on the same grid as the input raster
- `zonal_stats.json` — JSON array with one object per zone, each containing `zone_id`, `zone_name`, and for each index a statistics object with the keys specified in the config

The pipeline must correctly handle: CRS mismatch between raster and vector data, nodata propagation through band math (if any input band is nodata the output pixel must be nodata), division-by-zero in index formulas, valid-range clipping per index, zones that partially extend beyond the raster extent, and proper COG structure (internal tiling and overview pyramids as specified in the config).

Run: `python3 /app/pipeline.py`