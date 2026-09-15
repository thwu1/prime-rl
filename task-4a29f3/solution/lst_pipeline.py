#!/usr/bin/env python3
"""Land Surface Temperature pipeline — corrected analysis with diagnostic report.

Reads synthetic Landsat 8 bands from raw data, computes corrected outputs
including cloud masking, NDVI, emissivity estimation, LST computation,
zonal statistics, and a diagnostic report identifying errors in the
previous analyst's methodology.
"""


import numpy as np
from osgeo import gdal, osr
import json
import os

gdal.UseExceptions()


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def read_band(filepath):
    ds = gdal.Open(filepath)
    if ds is None:
        raise FileNotFoundError(filepath)
    data = ds.GetRasterBand(1).ReadAsArray()
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    ds = None
    return data, gt, proj


def write_geotiff(filepath, data, gt, proj, nodata=None):
    if data.dtype == bool:
        data = data.astype(np.uint8)
    gdal_dtype = {
        np.dtype('uint8'): gdal.GDT_Byte,
        np.dtype('uint16'): gdal.GDT_UInt16,
        np.dtype('float32'): gdal.GDT_Float32,
        np.dtype('float64'): gdal.GDT_Float32,
    }.get(data.dtype, gdal.GDT_Float32)
    if data.dtype == np.float64:
        data = data.astype(np.float32)
    nrows, ncols = data.shape
    driver = gdal.GetDriverByName('GTiff')
    ds = driver.Create(filepath, ncols, nrows, 1, gdal_dtype)
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(float(nodata))
    band.WriteArray(data)
    band.FlushCache()
    ds = None


# ---------------------------------------------------------------------------
# Diagnostic analysis — identify errors from raw data and methodology
# ---------------------------------------------------------------------------

def diagnose_errors(qa):
    """Identify processing errors by analyzing raw QA data and comparing
    against correct methodology."""
    errors = []

    # Error 1: Incomplete quality masking
    # A cloud-only mask (bit 3) misses fill, shadow, and snow pixels.
    # Count how many contaminated pixels each category contributes.
    fill_pixels = int(np.sum((qa & (1 << 0)) != 0))
    cloud_pixels = int(np.sum((qa & (1 << 3)) != 0))
    shadow_pixels = int(np.sum((qa & (1 << 4)) != 0))
    snow_pixels = int(np.sum((qa & (1 << 5)) != 0))
    missed = fill_pixels + shadow_pixels + snow_pixels

    errors.append({
        "category": "incomplete_quality_masking",
        "description": (
            "The QA mask only checks the cloud flag (bit 3) and misses fill pixels "
            f"(bit 0, {fill_pixels} pixels), cloud shadow (bit 4, {shadow_pixels} "
            f"pixels), and snow/ice (bit 5, {snow_pixels} pixels). This leaves "
            f"{missed} contaminated pixels unmasked, including shadow regions "
            "and image fill edges that contain invalid data."
        )
    })

    # Error 2: Spatially uniform emissivity
    errors.append({
        "category": "uniform_emissivity_assumption",
        "description": (
            "A spatially uniform emissivity value was applied across the entire scene "
            "regardless of land cover type. Different surfaces (water, bare soil, "
            "vegetation, urban) have significantly different thermal emissivities. "
            "Emissivity should be estimated from spectral indices like NDVI to account "
            "for spatial variation in surface properties."
        )
    })

    # Error 3: Missing emissivity correction in LST
    errors.append({
        "category": "missing_lst_emissivity_correction",
        "description": (
            "The output labeled as LST is actually brightness temperature without "
            "emissivity correction. Brightness temperature assumes blackbody emission "
            "(emissivity=1), which systematically overestimates temperature for real "
            "surfaces. A single-channel emissivity correction must be applied to convert "
            "brightness temperature to true land surface temperature."
        )
    })

    return errors


# ---------------------------------------------------------------------------
# Corrected pipeline
# ---------------------------------------------------------------------------

def compute_valid_mask(qa):
    bad_bits = (1 << 0) | (1 << 3) | (1 << 4) | (1 << 5)
    return (qa & bad_bits) == 0


def compute_ndvi(red, nir):
    r = red.astype(np.float64)
    n = nir.astype(np.float64)
    with np.errstate(divide='ignore', invalid='ignore'):
        ndvi = (n - r) / (n + r)
    return ndvi.astype(np.float32)


def compute_emissivity(ndvi):
    eps_s = 0.964
    eps_v = 0.984
    C = 0.005
    ndvi_s = 0.2
    ndvi_v = 0.5
    e = np.full_like(ndvi, np.nan, dtype=np.float32)
    e[ndvi < 0] = 0.991
    e[(ndvi >= 0) & (ndvi < ndvi_s)] = eps_s
    e[ndvi > ndvi_v] = eps_v + C
    m = (ndvi >= ndvi_s) & (ndvi <= ndvi_v)
    Pv = ((ndvi[m] - ndvi_s) / (ndvi_v - ndvi_s)) ** 2
    e[m] = (eps_v * Pv + eps_s * (1 - Pv) + C).astype(np.float32)
    return e


def compute_lst(thermal_dn, emissivity, mtl):
    p = mtl["LANDSAT_METADATA_FILE"]
    M_L = p["LEVEL1_RADIOMETRIC_RESCALING"]["RADIANCE_MULT_BAND_10"]
    A_L = p["LEVEL1_RADIOMETRIC_RESCALING"]["RADIANCE_ADD_BAND_10"]
    K1 = p["LEVEL1_THERMAL_CONSTANTS"]["K1_CONSTANT_BAND_10"]
    K2 = p["LEVEL1_THERMAL_CONSTANTS"]["K2_CONSTANT_BAND_10"]
    lam = p["TIRS_THERMAL_CONSTANTS"]["BAND_10_CENTRAL_WAVELENGTH_UM"]
    rho = 14388.0
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        radiance = M_L * thermal_dn.astype(np.float64) + A_L
        bt_k = K2 / np.log(K1 / radiance + 1.0)
        lst_k = bt_k / (1.0 + (lam * bt_k / rho) * np.log(emissivity.astype(np.float64)))
    return (lst_k - 273.15).astype(np.float32)


def geo_to_pixel(x, y, gt):
    col = int((x - gt[0]) / gt[1])
    row = int((gt[3] - y) / (-gt[5]))
    return row, col


def compute_zonal_stats(lst, valid_mask, regions_path, gt):
    with open(regions_path) as f:
        regions = json.load(f)
    shape = lst.shape
    stats = {}
    for feat in regions['features']:
        name = feat['properties']['name']
        coords = feat['geometry']['coordinates'][0]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        r1, c1 = geo_to_pixel(min(xs), max(ys), gt)
        r2, c2 = geo_to_pixel(max(xs), min(ys), gt)
        r1, r2 = max(0, r1), min(shape[0], r2)
        c1, c2 = max(0, c1), min(shape[1], c2)
        zone = np.zeros(shape, dtype=bool)
        zone[r1:r2, c1:c2] = True
        valid_in_zone = zone & valid_mask & ~np.isnan(lst)
        if valid_in_zone.sum() > 0:
            zv = lst[valid_in_zone]
            stats[name] = {
                "mean_lst_celsius": round(float(np.mean(zv)), 4),
                "min_lst_celsius": round(float(np.min(zv)), 4),
                "max_lst_celsius": round(float(np.max(zv)), 4),
                "valid_pixel_count": int(valid_in_zone.sum()),
            }
        else:
            stats[name] = {
                "mean_lst_celsius": None,
                "min_lst_celsius": None,
                "max_lst_celsius": None,
                "valid_pixel_count": 0,
            }
    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    data_dir = '/app/data'
    out_dir = '/app/output'
    os.makedirs(out_dir, exist_ok=True)

    # Read input bands
    red, gt, proj = read_band(f'{data_dir}/LC08_B4_RED.tif')
    nir, _, _ = read_band(f'{data_dir}/LC08_B5_NIR.tif')
    thermal, _, _ = read_band(f'{data_dir}/LC08_B10_THERMAL.tif')
    qa, _, _ = read_band(f'{data_dir}/LC08_QA_PIXEL.tif')

    with open(f'{data_dir}/LC08_MTL.json') as f:
        mtl = json.load(f)

    # Diagnose errors from raw QA data
    errors = diagnose_errors(qa)

    # Produce corrected outputs
    mask = compute_valid_mask(qa)
    write_geotiff(f'{out_dir}/valid_mask.tif', mask.astype(np.uint8), gt, proj)

    ndvi = compute_ndvi(red, nir)
    ndvi[~mask] = np.nan
    write_geotiff(f'{out_dir}/ndvi.tif', ndvi, gt, proj, nodata=np.nan)

    emissivity = compute_emissivity(ndvi)
    emissivity[~mask] = np.nan
    write_geotiff(f'{out_dir}/emissivity.tif', emissivity, gt, proj, nodata=np.nan)

    lst = compute_lst(thermal, emissivity, mtl)
    lst[~mask] = np.nan
    write_geotiff(f'{out_dir}/lst_celsius.tif', lst, gt, proj, nodata=np.nan)

    stats = compute_zonal_stats(lst, mask, f'{data_dir}/regions.geojson', gt)
    with open(f'{out_dir}/zonal_stats.json', 'w') as f:
        json.dump(stats, f, indent=2)

    # Write diagnostic report
    report = {
        "errors_found": errors,
        "corrections_applied": [
            {
                "category": "comprehensive_quality_masking",
                "description": (
                    "Applied complete QA_PIXEL bit decoding, checking fill (bit 0), "
                    "cloud (bit 3), cloud shadow (bit 4), and snow/ice (bit 5) flags "
                    "to exclude all contaminated pixels."
                )
            },
            {
                "category": "ndvi_based_emissivity_estimation",
                "description": (
                    "Estimated land surface emissivity using the NDVI Threshold Method "
                    "with distinct regimes for water (NDVI<0), bare soil (NDVI<0.2), "
                    "mixed (0.2-0.5), and full vegetation (NDVI>0.5) surfaces."
                )
            },
            {
                "category": "emissivity_corrected_lst",
                "description": (
                    "Applied mono-window single-channel emissivity correction to derive "
                    "true land surface temperature from brightness temperature using "
                    "Band 10 spectral characteristics and estimated emissivity."
                )
            }
        ]
    }

    with open(f'{out_dir}/diagnostic_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print("Corrected LST pipeline completed.")
    for name, s in stats.items():
        if s['mean_lst_celsius'] is not None:
            print(f"  {name}: mean={s['mean_lst_celsius']:.2f} C, "
                  f"count={s['valid_pixel_count']}")
    print(f"  Diagnostic report: {len(errors)} errors identified")


if __name__ == '__main__':
    main()
