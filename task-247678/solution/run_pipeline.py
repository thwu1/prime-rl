#!/usr/bin/env python3
"""
Multi-criteria site suitability analysis pipeline with candidate patch identification.
"""
import json
import os
import subprocess
import sys

import numpy as np
from osgeo import gdal, ogr
from scipy import ndimage


def run(cmd):
    """Run a shell command, raising on failure."""
    print(f"  >> {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"STDERR: {result.stderr}", file=sys.stderr)
        raise RuntimeError(f"Command failed (exit {result.returncode}): {cmd}")
    return result.stdout


def main():
    os.chdir('/app')
    os.makedirs('output', exist_ok=True)

    # ---- Load configuration ----
    config_path = '/app/criteria.json'
    print(f"Loading config from: {config_path}")
    with open(config_path, 'r') as f:
        config = json.load(f)

    print(f"Config keys: {list(config.keys())}")

    required_keys = ['analysis', 'criteria', 'candidate_analysis', 'output']
    for key in required_keys:
        if key not in config:
            raise KeyError(f"Missing required key '{key}' in {config_path}")

    res = config['analysis']['resolution_m']
    ca = config['candidate_analysis']
    threshold = ca['suitability_threshold']
    min_area_ha = ca['min_contiguous_area_ha']
    connectivity = ca['connectivity']

    # ---- Get extent from boundary layer ----
    ds = ogr.Open('/app/site_data.gpkg')
    lyr = ds.GetLayerByName('boundary')
    extent = lyr.GetExtent()  # (xmin, xmax, ymin, ymax)
    xmin, xmax, ymin, ymax = extent
    ds = None
    te = f"{xmin} {ymin} {xmax} {ymax}"
    print(f"Analysis extent: {te}")
    print(f"Resolution: {res}m")

    # ---- Rasterize vector layers ----
    print("\n=== Rasterizing vector layers ===")
    run(f'gdal_rasterize -burn 1 -tr {res} {res} -te {te} '
        f'-ot Int16 -init 0 '
        f'site_data.gpkg -l hospitals hospitals.tif')

    run(f'gdal_rasterize -burn 1 -tr {res} {res} -te {te} '
        f'-ot Int16 -init 0 '
        f'site_data.gpkg -l roads roads.tif')

    run(f'gdal_rasterize -burn 1 -tr {res} {res} -te {te} '
        f'-ot Int16 -init 0 '
        f'site_data.gpkg -l flood_zones flood_zones.tif')

    # ---- Compute proximity rasters ----
    print("\n=== Computing proximity rasters ===")
    run('gdal_proximity.py hospitals.tif hospitals_proximity.tif '
        '-distunits GEO -ot Float32')

    run('gdal_proximity.py roads.tif roads_proximity.tif '
        '-distunits GEO -ot Float32')

    # ---- Reclassify each criterion ----
    print("\n=== Reclassifying criteria ===")

    # Hospital proximity: far = good (100), close = bad (10)
    run('gdal_calc.py -A hospitals_proximity.tif '
        '--outfile hospitals_reclass.tif '
        '--calc="100*(A>500) + 50*((A>200)*(A<=500)) + 10*(A<=200)" '
        '--NoDataValue=0 --type=Float32')

    # Road proximity: close = good (100), far = bad (10)
    run('gdal_calc.py -A roads_proximity.tif '
        '--outfile roads_reclass.tif '
        '--calc="100*(A<=100) + 50*((A>100)*(A<=300)) + 10*(A>300)" '
        '--NoDataValue=0 --type=Float32')

    # Flood risk: outside = good (100), inside = bad (10)
    run('gdal_calc.py -A flood_zones.tif '
        '--outfile flood_reclass.tif '
        '--calc="100*(A==0) + 10*(A>=1)" '
        '--NoDataValue=0 --type=Float32')

    # ---- Weighted overlay ----
    print("\n=== Weighted overlay ===")
    # weights: hospital=3, road=2, flood=5, total=10
    run('gdal_calc.py '
        '-A hospitals_reclass.tif '
        '-B roads_reclass.tif '
        '-C flood_reclass.tif '
        '--outfile output/suitability.tif '
        '--calc="(3*A + 2*B + 5*C)/10" '
        '--NoDataValue=0 --type=Float32')

    # ---- Load suitability raster for analysis ----
    print("\n=== Analyzing suitability raster ===")
    ds = gdal.Open('output/suitability.tif')
    band = ds.GetRasterBand(1)
    data = band.ReadAsArray().astype(float)
    gt = ds.GetGeoTransform()
    nodata = band.GetNoDataValue()

    if nodata is not None:
        valid_mask = data != nodata
    else:
        valid_mask = np.ones_like(data, dtype=bool)

    valid = data[valid_mask]

    # ---- Connected component analysis for candidate patches ----
    print("\n=== Candidate patch analysis ===")
    print(f"Threshold: {threshold}, Min area: {min_area_ha} ha, Connectivity: {connectivity}")

    above_mask = (data > threshold) & valid_mask

    # Build connectivity structure
    if connectivity == 4:
        structure = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]])
    else:
        structure = np.ones((3, 3), dtype=int)

    labels, num_features = ndimage.label(above_mask, structure=structure)
    pixel_area_ha = abs(gt[1] * gt[5]) / 10000.0  # 50*50=2500 sq m = 0.25 ha

    print(f"Found {num_features} connected components above threshold {threshold}")
    print(f"Pixel area: {pixel_area_ha} ha")

    candidates = []
    for label_id in range(1, num_features + 1):
        mask = labels == label_id
        pixel_count = int(np.sum(mask))
        area_ha = pixel_count * pixel_area_ha

        if area_ha < min_area_ha:
            continue

        patch_vals = data[mask]
        mean_suit = round(float(np.mean(patch_vals)), 2)
        max_suit = float(np.max(patch_vals))

        # Geometric centroid of pixel centers
        rows, cols = np.where(mask)
        mean_col = float(np.mean(cols))
        mean_row = float(np.mean(rows))
        cx = round(gt[0] + (mean_col + 0.5) * gt[1], 1)
        cy = round(gt[3] + (mean_row + 0.5) * gt[5], 1)

        candidates.append({
            'patch_id': 0,
            'centroid_x': cx,
            'centroid_y': cy,
            'area_ha': round(area_ha, 2),
            'mean_suitability': mean_suit,
            'max_suitability': max_suit
        })

    # Sort by mean_suitability descending
    candidates.sort(key=lambda x: x['mean_suitability'], reverse=True)
    for i, c in enumerate(candidates):
        c['patch_id'] = i + 1

    print(f"Qualifying patches (>= {min_area_ha} ha): {len(candidates)}")

    # ---- Write candidates.json ----
    with open('output/candidates.json', 'w') as f:
        json.dump(candidates, f, indent=2)

    # ---- Compute summary statistics ----
    total_suitable_pixels = int(np.sum(above_mask))
    total_suitable_area_ha = round(total_suitable_pixels * pixel_area_ha, 2)
    mean_suitability_all = round(float(np.mean(valid)), 2)

    best = candidates[0] if candidates else None
    results = {
        'total_suitable_area_ha': total_suitable_area_ha,
        'num_candidate_patches': len(candidates),
        'best_candidate': {
            'patch_id': best['patch_id'],
            'centroid_x': best['centroid_x'],
            'centroid_y': best['centroid_y'],
            'area_ha': best['area_ha'],
            'mean_suitability': best['mean_suitability']
        } if best else None,
        'mean_suitability_all': mean_suitability_all
    }

    with open('output/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    ds = None

    print("\nResults:")
    print(json.dumps(results, indent=2))

    # Clean up intermediate files
    for fname in ['hospitals.tif', 'roads.tif', 'flood_zones.tif',
                  'hospitals_proximity.tif', 'roads_proximity.tif',
                  'hospitals_reclass.tif', 'roads_reclass.tif', 'flood_reclass.tif']:
        if os.path.exists(fname):
            os.remove(fname)

    print("\nDone.")


if __name__ == '__main__':
    main()
