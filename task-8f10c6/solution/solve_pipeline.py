#!/usr/bin/env python3
"""Geospatial raster analysis pipeline: spectral indices, COG output, zonal stats."""

import json
import os
import re
import warnings

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.mask import mask as rasterio_mask
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform


def evaluate_formula(formula, bands, nodata_in, output_nodata):
    """Evaluate a band-math formula string on numpy arrays.

    Args:
        formula: expression using b1..b6 variables (e.g. "(b6 - b4) / (b6 + b4)")
        bands: dict mapping 'b1'..'b6' to float64 numpy arrays
        nodata_in: input nodata value
        output_nodata: value to write for nodata pixels in output

    Returns:
        float64 numpy array with the computed index
    """
    # Determine which bands the formula references
    used_band_ids = set(re.findall(r'b(\d+)', formula))

    # Build nodata mask: True where ANY referenced band is nodata
    first_band = next(iter(bands.values()))
    nodata_mask = np.zeros(first_band.shape, dtype=bool)
    for bid in used_band_ids:
        nodata_mask |= (bands[f'b{bid}'] == nodata_in)

    # Replace nodata pixels with a safe placeholder to avoid nan during eval
    clean = {}
    for key, arr in bands.items():
        c = arr.copy()
        c[nodata_mask] = 1.0
        clean[key] = c

    # Evaluate the formula
    ns = {f'b{i}': clean[f'b{i}'] for i in range(1, 7)}
    with np.errstate(divide='ignore', invalid='ignore'):
        result = eval(formula, {"__builtins__": {}}, ns)  # noqa: S307

    # Mark inf/nan as nodata (catches division by zero)
    bad = np.isinf(result) | np.isnan(result)
    nodata_mask |= bad

    result[nodata_mask] = output_nodata
    return result


def create_cog(data, profile, output_path, cog_opts):
    """Write a numpy array as a tiled GeoTIFF with overview pyramids."""
    blocksize = cog_opts['blocksize']
    factors = cog_opts['overview_factors']
    resamp = getattr(Resampling, cog_opts['overview_resampling'])

    out_profile = profile.copy()
    out_profile.update({
        'driver': 'GTiff',
        'tiled': True,
        'blockxsize': blocksize,
        'blockysize': blocksize,
        'compress': 'deflate',
    })

    with rasterio.open(output_path, 'w', **out_profile) as dst:
        dst.write(data)

    with rasterio.open(output_path, 'r+') as dst:
        dst.build_overviews(factors, resamp)
        dst.update_tags(ns='rio_overview',
                        resampling=cog_opts['overview_resampling'])


def transform_geometry(geom, src_crs, dst_crs):
    """Reproject a shapely geometry between CRS."""
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    return shapely_transform(transformer.transform, geom)


def compute_zone_stats(index_path, zones_geojson, zone_crs, raster_crs, stat_names):
    """Compute per-zone statistics for a single index raster."""
    results = []

    with rasterio.open(index_path) as src:
        nodata = src.nodata

        for feat in zones_geojson:
            zid = feat['properties']['zone_id']
            zname = feat['properties']['zone_name']

            geom = shape(feat['geometry'])

            # Transform zone geometry to raster CRS if needed
            if zone_crs != raster_crs:
                geom = transform_geometry(geom, zone_crs, raster_crs)

            geom_json = mapping(geom)

            try:
                masked_data, _ = rasterio_mask(
                    src, [geom_json], crop=True, nodata=nodata,
                )
                band = masked_data[0]
                valid = band[band != nodata]
                valid = valid[~np.isnan(valid) & ~np.isinf(valid)]
            except Exception:
                valid = np.array([], dtype=np.float64)

            if len(valid) == 0:
                zone_stats = {s: None for s in stat_names}
                zone_stats['count'] = 0
            else:
                zone_stats = {}
                for s in stat_names:
                    if s == 'mean':
                        zone_stats[s] = float(np.mean(valid))
                    elif s == 'std':
                        zone_stats[s] = float(np.std(valid))
                    elif s == 'min':
                        zone_stats[s] = float(np.min(valid))
                    elif s == 'max':
                        zone_stats[s] = float(np.max(valid))
                    elif s == 'median':
                        zone_stats[s] = float(np.median(valid))
                    elif s == 'count':
                        zone_stats[s] = int(len(valid))

            results.append({'zone_id': zid, 'zone_name': zname, 'stats': zone_stats})

    return results


def main():
    warnings.filterwarnings('ignore', category=RuntimeWarning)

    # Load configuration
    with open('/app/data/analysis_config.json') as f:
        config = json.load(f)

    # Load input raster
    with rasterio.open('/app/data/multiband.tif') as src:
        raster_data = src.read()
        raster_profile = src.profile.copy()
        nodata_in = src.nodata
        raster_crs = str(src.crs)

    # Prepare band arrays (float64 for precision)
    bands = {}
    for i in range(1, 7):
        bands[f'b{i}'] = raster_data[i - 1].astype(np.float64)

    # Output settings
    output_nodata = config['output_nodata']
    cog_opts = config['cog_options']
    stat_names = config['statistics']

    index_profile = raster_profile.copy()
    index_profile.update({
        'count': 1,
        'dtype': 'float32',
        'nodata': output_nodata,
    })

    os.makedirs('/app/output/indices', exist_ok=True)

    # Compute and write each spectral index
    for idx_name, idx_cfg in config['indices'].items():
        formula = idx_cfg['formula']
        valid_range = idx_cfg.get('valid_range')

        result = evaluate_formula(formula, bands, nodata_in, output_nodata)

        # Clip to valid range
        if valid_range:
            vmask = result != output_nodata
            result[vmask] = np.clip(result[vmask], valid_range[0], valid_range[1])

        out_path = f'/app/output/indices/{idx_name}.tif'
        out_arr = result.astype(np.float32)[np.newaxis, :, :]
        create_cog(out_arr, index_profile, out_path, cog_opts)
        print(f"  Wrote {out_path}")

    # Load zones
    with open('/app/data/zones.geojson') as f:
        zones_data = json.load(f)

    zone_features = zones_data['features']
    zone_crs = 'EPSG:4326'  # GeoJSON is always WGS84

    # Compute zonal statistics for each index
    all_stats = []
    for feat in zone_features:
        all_stats.append({
            'zone_id': feat['properties']['zone_id'],
            'zone_name': feat['properties']['zone_name'],
        })

    for idx_name in config['indices']:
        idx_path = f'/app/output/indices/{idx_name}.tif'
        idx_results = compute_zone_stats(
            idx_path, zone_features, zone_crs, raster_crs, stat_names,
        )
        for i, zr in enumerate(idx_results):
            all_stats[i][idx_name] = zr['stats']

    # Write zonal statistics
    with open('/app/output/zonal_stats.json', 'w') as f:
        json.dump(all_stats, f, indent=2)
    print(f"  Wrote /app/output/zonal_stats.json")

    print("Pipeline complete.")


if __name__ == '__main__':
    main()
