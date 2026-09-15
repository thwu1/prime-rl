A Landsat 8 OLI/TIRS dataset is staged at `/data/landsat/`. It includes surface reflectance bands (`SR_B4.tif` Red, `SR_B5.tif` NIR), a Level-1 thermal band (`B10_L1.tif`), a quality assessment band (`QA_PIXEL.tif`), a DEM (`DEM.tif`), radiometric calibration metadata (`MTL.json`), analysis zone polygons (`zones.geojson`), and a processing parameters file (`parameters.json`).

Produce the following outputs in `/app/output/`:

1. **`cloud_mask.tif`** — Binary UInt8 raster identifying all atmospherically contaminated pixels. 1 = contaminated, 0 = clear.

2. **`ndvi.tif`** — Normalized Difference Vegetation Index from calibrated surface reflectance. Contaminated pixels must be set to nodata. Float32.

3. **`lst_kelvin.tif`** — Land Surface Temperature in Kelvin with appropriate emissivity correction applied. Contaminated pixels must be set to nodata. Float32.

4. **`slope.tif`** — Terrain slope in degrees derived from the DEM. Float32.

5. **`zonal_stats.json`** — JSON object keyed by zone name from `zones.geojson`. Per zone: `mean_lst`, `mean_ndvi`, `cloud_fraction`, `mean_slope`, `clear_pixel_count`, `total_pixel_count`, `lst_p10`, `lst_p50`, `lst_p90` (10th/50th/90th percentile of LST). Temperature and vegetation statistics must exclude contaminated pixels.

All raster outputs must preserve the source CRS (EPSG:32610) and spatial dimensions (100x100).