A multispectral environmental survey dataset resides in `/app/data/`. The raster imagery's spectral band labels were lost during data processing — no wavelength calibration is available. The directory also contains vector zone boundaries, point sample locations, and project metadata.

Explore the data directory, characterize every dataset's geospatial properties, determine the spectral identity (Red, Green, Blue, NIR) of each raster band through radiometric analysis, and produce a complete vegetation and water analysis. Handle any data quality or coordinate reference issues you encounter.

Write all outputs to `/app/output/`:

- `band_mapping.json`: `{"red": <int>, "green": <int>, "blue": <int>, "nir": <int>}` — 0-based band indices identifying which raster band corresponds to each spectral channel.

- `zonal_stats.csv`: Columns `zone_id,ndvi_mean,ndvi_std,ndvi_median,ndwi_mean,ndwi_std,ndwi_median,valid_pixels`. NDVI=(NIR-Red)/(NIR+Red), NDWI=(Green-NIR)/(Green+NIR). Population standard deviation (ddof=0). Sorted by zone_id, floats to 6 decimal places. Include all zones from the vector file. Exclude corrupted or invalid pixels from statistics.

- `station_values.csv`: Columns `station_id,zone_id,ndvi,ndwi`. Spectral indices at each sample point via bilinear interpolation. Point-in-polygon zone assignment. Sorted by station_id, floats to 6 decimal places.

- `correlation.json`: `{"ndvi_pearson_r": <float>, "ndwi_pearson_r": <float>}` — Pearson correlation between per-station spectral index values and the mean index of each station's assigned zone. Rounded to 6 decimal places.