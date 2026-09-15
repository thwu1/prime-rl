#!/usr/bin/env python3
"""Reference solution — terrain data quality audit and suitability assessment.

"""

import csv
import json
import os
import subprocess
import numpy as np
from osgeo import gdal, osr, ogr
from scipy import ndimage


# -----------------------------------------------------------------------
# Step 1: Diagnose and correct DEM quality issues
# -----------------------------------------------------------------------

def load_control_points():
    pts = []
    with open('/app/control_points.csv') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pts.append({
                'easting': float(row['easting']),
                'northing': float(row['northing']),
                'elevation_m': float(row['elevation_m']),
            })
    return pts


def calibrate_dem():
    """Detect vertical bias and nodata contamination, write corrected DEM."""
    ds = gdal.Open('/app/dem.tif')
    gt = ds.GetGeoTransform()
    ny, nx = ds.RasterYSize, ds.RasterXSize
    proj = ds.GetProjection()
    raw = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    ds = None

    # --- Detect nodata contamination ---
    # Values <= -9000 are clearly anomalous for a DEM in this region
    nodata_mask = raw <= -9000.0
    num_nodata = int(np.sum(nodata_mask))
    print(f"  Detected {num_nodata} nodata-contaminated pixels")

    # --- Detect vertical bias via control points ---
    control_pts = load_control_points()
    residuals = []
    for cp in control_pts:
        col = int((cp['easting'] - gt[0]) / gt[1])
        row = int((cp['northing'] - gt[3]) / gt[5])
        if 0 <= row < ny and 0 <= col < nx and not nodata_mask[row, col]:
            dem_val = raw[row, col]
            residuals.append(dem_val - cp['elevation_m'])

    bias = float(np.median(residuals))
    print(f"  Detected vertical bias: {bias:.2f} m "
          f"(from {len(residuals)} control points)")

    # --- Apply corrections ---
    corrected = raw - bias
    corrected[nodata_mask] = -9999.0

    # --- Write calibrated DEM ---
    os.makedirs('/app/output', exist_ok=True)
    drv = gdal.GetDriverByName('GTiff')
    out_ds = drv.Create('/app/output/dem_calibrated.tif', nx, ny, 1,
                        gdal.GDT_Float32)
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    band = out_ds.GetRasterBand(1)
    band.SetNoDataValue(-9999.0)
    band.WriteArray(corrected.astype(np.float32))
    band.FlushCache()
    out_ds = None

    return gt, ny, nx, proj


# -----------------------------------------------------------------------
# Step 2: Compute terrain derivatives from calibrated DEM
# -----------------------------------------------------------------------

def compute_derivatives():
    os.makedirs('/app/output', exist_ok=True)
    for product, extra_args in [
        ('slope', ['-compute_edges']),
        ('aspect', ['-zero_for_flat', '-compute_edges']),
        ('TRI', ['-compute_edges']),
    ]:
        out_name = product.lower() if product != 'TRI' else 'tri'
        cmd = [
            'gdaldem', product, '/app/output/dem_calibrated.tif',
            f'/app/output/{out_name}.tif', '-of', 'GTiff',
        ] + extra_args
        subprocess.run(cmd, check=True, capture_output=True)


def read_raster(path):
    ds = gdal.Open(path)
    arr = ds.GetRasterBand(1).ReadAsArray()
    ds = None
    return arr


# -----------------------------------------------------------------------
# Step 3: Diagnose and fix exclusion zone coordinates
# -----------------------------------------------------------------------

def load_exclusion_zones_utm(gt, ny, nx):
    """Read exclusion zones, detect coordinate swap, return UTM coords."""
    with open('/app/exclusion_zones.geojson') as f:
        data = json.load(f)

    srs_wgs = osr.SpatialReference()
    srs_wgs.ImportFromEPSG(4326)
    srs_wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    srs_utm = osr.SpatialReference()
    srs_utm.ImportFromEPSG(32633)
    srs_utm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(srs_wgs, srs_utm)

    min_e = gt[0]
    max_e = gt[0] + nx * gt[1]
    max_n = gt[3]
    min_n = gt[3] + ny * gt[5]

    utm_points = []
    for feat in data['features']:
        coords = feat['geometry']['coordinates']
        lon, lat = coords[0], coords[1]

        # Try as-is (GeoJSON standard: [lon, lat])
        pt = ogr.Geometry(ogr.wkbPoint)
        pt.AddPoint(lon, lat)
        pt.Transform(ct)
        e, n = pt.GetX(), pt.GetY()
        in_extent = min_e <= e <= max_e and min_n <= n <= max_n

        if not in_extent:
            # Try swapped: maybe coordinates are [lat, lon]
            pt2 = ogr.Geometry(ogr.wkbPoint)
            pt2.AddPoint(lat, lon)
            pt2.Transform(ct)
            e2, n2 = pt2.GetX(), pt2.GetY()
            if min_e <= e2 <= max_e and min_n <= n2 <= max_n:
                print(f"  Exclusion point {feat['properties'].get('id')}: "
                      f"detected lat/lon swap, correcting")
                e, n = e2, n2

        utm_points.append((e, n))

    return utm_points


# -----------------------------------------------------------------------
# Step 4: Build suitability mask
# -----------------------------------------------------------------------

def build_exclusion_mask(gt, ny, nx, excl_utm, excl_buf_m):
    pixel_size = gt[1]
    excl_buf_px = excl_buf_m / pixel_size
    mask = np.ones((ny, nx), dtype=bool)
    Y_grid, X_grid = np.ogrid[:ny, :nx]

    for e_utm, n_utm in excl_utm:
        col = (e_utm - gt[0]) / gt[1]
        row = (n_utm - gt[3]) / gt[5]
        dist = np.sqrt((X_grid - col)**2 + (Y_grid - row)**2)
        mask &= dist > excl_buf_px

    return mask


def label_regions(suitable, connectivity):
    if connectivity == 8:
        struct = ndimage.generate_binary_structure(2, 2)
    else:
        struct = ndimage.generate_binary_structure(2, 1)
    return ndimage.label(suitable, structure=struct)


# -----------------------------------------------------------------------
# Step 5: Compute region metrics and score
# -----------------------------------------------------------------------

def compute_region_metrics(region_mask, dem, slope, aspect, gt):
    rows, cols = np.where(region_mask)
    pixel_count = len(rows)
    pixel_area = gt[1] ** 2
    area_m2 = pixel_count * pixel_area

    centroid_row = float(np.mean(rows))
    centroid_col = float(np.mean(cols))
    centroid_e = gt[0] + centroid_col * gt[1] + centroid_row * gt[2]
    centroid_n = gt[3] + centroid_col * gt[4] + centroid_row * gt[5]

    srs_utm = osr.SpatialReference()
    srs_utm.ImportFromEPSG(32633)
    srs_utm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    srs_wgs = osr.SpatialReference()
    srs_wgs.ImportFromEPSG(4326)
    srs_wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    ct = osr.CoordinateTransformation(srs_utm, srs_wgs)
    pt = ogr.Geometry(ogr.wkbPoint)
    pt.AddPoint(centroid_e, centroid_n)
    pt.Transform(ct)
    centroid_lon, centroid_lat = pt.GetX(), pt.GetY()

    mean_elevation = float(np.mean(dem[rows, cols]))
    mean_slope = float(np.mean(slope[rows, cols]))
    mean_aspect = float(np.mean(aspect[rows, cols]))

    aspect_rad = np.deg2rad(aspect[rows, cols].astype(np.float64))
    R = float(np.sqrt(np.mean(np.cos(aspect_rad))**2
                       + np.mean(np.sin(aspect_rad))**2))

    return {
        'pixel_count': int(pixel_count),
        'area_m2': float(area_m2),
        'centroid_utm_e': float(centroid_e),
        'centroid_utm_n': float(centroid_n),
        'centroid_lon': float(centroid_lon),
        'centroid_lat': float(centroid_lat),
        'mean_elevation': mean_elevation,
        'mean_slope': mean_slope,
        'mean_aspect': mean_aspect,
        'aspect_uniformity': R,
    }


def score_regions(region_data, scoring_config):
    weights = scoring_config['weights']
    tie_value = scoring_config.get('tie_value', 0.5)
    metrics = list(weights.keys())

    if len(region_data) == 0:
        return

    for m in metrics:
        values = [r[m] for r in region_data]
        lo, hi = min(values), max(values)
        for r in region_data:
            if hi == lo:
                r[f'_norm_{m}'] = tie_value
            else:
                r[f'_norm_{m}'] = (r[m] - lo) / (hi - lo)

    for r in region_data:
        r['score'] = sum(weights[m] * r[f'_norm_{m}'] for m in metrics)

    for r in region_data:
        for m in metrics:
            del r[f'_norm_{m}']


# -----------------------------------------------------------------------
# Main pipeline
# -----------------------------------------------------------------------

def main():
    print("=== Terrain Data Quality Audit and Suitability Assessment ===\n")

    # Load specification
    with open('/app/site_spec.json') as f:
        spec = json.load(f)

    # Step 1: Calibrate DEM
    print("Step 1: DEM quality audit and calibration")
    gt, ny, nx, proj = calibrate_dem()

    # Step 2: Compute terrain derivatives
    print("\nStep 2: Computing terrain derivatives from calibrated DEM")
    compute_derivatives()

    # Step 3: Load and fix exclusion zones
    print("\nStep 3: Loading and validating exclusion zones")
    excl_utm = load_exclusion_zones_utm(gt, ny, nx)

    # Step 4: Build suitability mask
    print("\nStep 4: Building suitability mask")
    dem_ds = gdal.Open('/app/output/dem_calibrated.tif')
    dem = dem_ds.GetRasterBand(1).ReadAsArray()
    dem_nodata = dem_ds.GetRasterBand(1).GetNoDataValue()
    dem_ds = None

    slope = read_raster('/app/output/slope.tif')
    aspect = read_raster('/app/output/aspect.tif')
    tri = read_raster('/app/output/tri.tif')
    pixel_area = gt[1] ** 2

    slope_min, slope_max = spec['slope_range_deg']
    aspect_min, aspect_max = spec['aspect_range_deg']
    elev_min, elev_max = spec['elevation_range_m']
    tri_max = spec['max_terrain_ruggedness_index']
    edge_buf = spec['edge_buffer_pixels']
    excl_buf = spec['exclusion_buffer_m']
    min_area = spec['min_contiguous_area_m2']
    connectivity = spec.get('connectivity', 8)
    scoring_config = spec['scoring']
    top_n = scoring_config['report_top_n']

    # Valid data mask (exclude nodata)
    valid_data = np.ones((ny, nx), dtype=bool)
    if dem_nodata is not None:
        valid_data &= dem != dem_nodata
    valid_data &= ~np.isnan(dem)

    slope_ok = (slope >= slope_min) & (slope <= slope_max)
    aspect_ok = (aspect >= aspect_min) & (aspect <= aspect_max) & (aspect > 0)
    elev_ok = (dem >= elev_min) & (dem <= elev_max)
    tri_ok = tri <= tri_max

    edge_mask = np.zeros((ny, nx), dtype=bool)
    edge_mask[edge_buf:ny - edge_buf, edge_buf:nx - edge_buf] = True

    excl_mask = build_exclusion_mask(gt, ny, nx, excl_utm, excl_buf)

    suitable = (valid_data & slope_ok & aspect_ok & elev_ok
                & tri_ok & edge_mask & excl_mask)

    # Connected component analysis
    labeled, num_features = label_regions(suitable, connectivity)
    min_pixels = min_area / pixel_area

    for rid in range(1, num_features + 1):
        if np.sum(labeled == rid) < min_pixels:
            suitable[labeled == rid] = False

    labeled, num_features = label_regions(suitable, connectivity)

    # Step 5: Compute metrics and score
    print(f"\nStep 5: Scoring {num_features} valid regions")
    region_data = []
    for rid in range(1, num_features + 1):
        rmask = labeled == rid
        metrics = compute_region_metrics(rmask, dem, slope, aspect, gt)
        metrics['region_id'] = int(rid)
        region_data.append(metrics)

    score_regions(region_data, scoring_config)
    region_data.sort(key=lambda r: r['score'], reverse=True)

    top_regions = region_data[:top_n]
    for i, r in enumerate(top_regions):
        r['rank'] = i + 1

    total_suitable = int(np.sum(suitable))

    results = {
        'total_suitable_pixels': total_suitable,
        'total_suitable_area_m2': float(total_suitable * pixel_area),
        'num_suitable_regions': len(region_data),
        'top_regions': top_regions,
        'optimal_region_id': (int(top_regions[0]['region_id'])
                              if top_regions else None),
    }

    # Write suitability raster
    drv = gdal.GetDriverByName('GTiff')
    out_ds = drv.Create('/app/output/suitability.tif', nx, ny, 1,
                        gdal.GDT_Byte)
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    out_ds.GetRasterBand(1).WriteArray(suitable.astype(np.uint8))
    out_ds.FlushCache()
    out_ds = None

    # Write results
    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n=== Analysis complete ===")
    print(f"  Suitable pixels: {total_suitable}")
    print(f"  Suitable area: {total_suitable * pixel_area:.0f} m2")
    print(f"  Valid regions: {len(region_data)}")
    if top_regions:
        print(f"  Optimal region: {results['optimal_region_id']} "
              f"(score={top_regions[0]['score']:.4f})")


if __name__ == '__main__':
    main()
