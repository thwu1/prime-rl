#!/usr/bin/env python3

"""Landsat LST processing pipeline — reference solution."""

import json
import math
import os

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()

DATA_DIR = "/data/landsat"
OUTPUT_DIR = "/app/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── read inputs ──────────────────────────────────────────────────────────


def read_raster(path):
    ds = gdal.Open(path)
    if ds is None:
        raise FileNotFoundError(path)
    return ds, ds.GetRasterBand(1).ReadAsArray()


b4_ds, b4 = read_raster(f"{DATA_DIR}/SR_B4.tif")
b5_ds, b5 = read_raster(f"{DATA_DIR}/SR_B5.tif")
b10_ds, b10 = read_raster(f"{DATA_DIR}/B10_L1.tif")
qa_ds, qa = read_raster(f"{DATA_DIR}/QA_PIXEL.tif")
dem_ds, dem = read_raster(f"{DATA_DIR}/DEM.tif")

with open(f"{DATA_DIR}/MTL.json") as fh:
    mtl = json.load(fh)
with open(f"{DATA_DIR}/parameters.json") as fh:
    params = json.load(fh)

rows, cols = b4_ds.RasterYSize, b4_ds.RasterXSize
gt = b4_ds.GetGeoTransform()
proj = b4_ds.GetProjection()


def write_raster(path, data, dtype, nodata=None):
    drv = gdal.GetDriverByName("GTiff")
    ds = drv.Create(path, cols, rows, 1, dtype)
    ds.SetGeoTransform(gt)
    ds.SetProjection(proj)
    band = ds.GetRasterBand(1)
    if nodata is not None:
        band.SetNoDataValue(nodata)
    band.WriteArray(data)
    band.FlushCache()
    ds = None


# ─── 1. cloud mask ───────────────────────────────────────────────────────
# Atmospheric contamination flags: dilated_cloud(1), cirrus(2), cloud(3),
# cloud_shadow(4). Extract from QA_PIXEL bit positions.
contamination_bits = [1, 2, 3, 4]
cloud_mask = np.zeros((rows, cols), dtype=np.uint8)
for bit_pos in contamination_bits:
    cloud_mask |= ((qa >> bit_pos) & 1).astype(np.uint8)
cloud_mask = (cloud_mask > 0).astype(np.uint8)

write_raster(f"{OUTPUT_DIR}/cloud_mask.tif", cloud_mask, gdal.GDT_Byte)
print(f"[1/5] cloud_mask.tif  — {int(cloud_mask.sum())} contaminated pixels")

# ─── 2. NDVI ─────────────────────────────────────────────────────────────

NODATA = float(params["nodata_value"])
sr_mult = params["surface_reflectance"]["scale_multiply"]
sr_add = params["surface_reflectance"]["scale_add"]

red = b4.astype(np.float64) * sr_mult + sr_add
nir = b5.astype(np.float64) * sr_mult + sr_add

denom = nir + red
ndvi = np.where(denom != 0.0, (nir - red) / denom, 0.0)

ndvi_out = ndvi.astype(np.float32).copy()
ndvi_out[cloud_mask == 1] = NODATA

write_raster(f"{OUTPUT_DIR}/ndvi.tif", ndvi_out, gdal.GDT_Float32, nodata=NODATA)
clear = cloud_mask == 0
print(f"[2/5] ndvi.tif       — range [{ndvi[clear].min():.4f}, {ndvi[clear].max():.4f}]")

# ─── 3. LST ──────────────────────────────────────────────────────────────

rescale = mtl["LANDSAT_METADATA_FILE"]["LEVEL1_RADIOMETRIC_RESCALING"]
therm = mtl["LANDSAT_METADATA_FILE"]["LEVEL1_THERMAL_CONSTANTS"]

rad_mult = rescale["RADIANCE_MULT_BAND_10"]
rad_add = rescale["RADIANCE_ADD_BAND_10"]
K1 = therm["K1_CONSTANT_BAND_10"]
K2 = therm["K2_CONSTANT_BAND_10"]

lam = params["thermal"]["wavelength_m"]
rho = params["thermal"]["rho_mK"]

em = params["emissivity"]
ndvi_s = em["ndvi_soil_threshold"]
ndvi_v = em["ndvi_vegetation_threshold"]
eps_s = em["emissivity_soil"]
eps_v = em["emissivity_vegetation"]

# DN → radiance
radiance = b10.astype(np.float64) * rad_mult + rad_add

# radiance → brightness temperature (Planck inversion)
bt = K2 / np.log(K1 / radiance + 1.0)

# emissivity from NDVI (three-regime threshold model)
pv = np.clip((ndvi - ndvi_s) / (ndvi_v - ndvi_s), 0.0, 1.0) ** 2
emissivity = np.where(
    ndvi <= ndvi_s,
    eps_s,
    np.where(ndvi >= ndvi_v, eps_v, 0.004 * pv + 0.986),
)

# LST = BT / (1 + (λ·BT/ρ)·ln(ε))
lst = bt / (1.0 + (lam * bt / rho) * np.log(emissivity))

lst_out = lst.astype(np.float32).copy()
lst_out[cloud_mask == 1] = NODATA

write_raster(f"{OUTPUT_DIR}/lst_kelvin.tif", lst_out, gdal.GDT_Float32, nodata=NODATA)
print(f"[3/5] lst_kelvin.tif — range [{lst[clear].min():.2f}, {lst[clear].max():.2f}] K")

# ─── 4. slope ─────────────────────────────────────────────────────────────

gdal.DEMProcessing(
    f"{OUTPUT_DIR}/slope.tif",
    dem_ds,
    "slope",
    format="GTiff",
    computeEdges=True,
)
slope_ds, slope = read_raster(f"{OUTPUT_DIR}/slope.tif")
print(f"[4/5] slope.tif      — range [{slope.min():.2f}, {slope.max():.2f}]°")

# ─── 5. zonal statistics ─────────────────────────────────────────────────

with open(f"{DATA_DIR}/zones.geojson") as fh:
    zones = json.load(fh)

zonal_stats = {}

for feat in zones["features"]:
    zname = feat["properties"]["zone_name"]

    # Build in-memory vector with one polygon
    mem_drv = ogr.GetDriverByName("Memory")
    mem_src = mem_drv.CreateDataSource("")
    srs = osr.SpatialReference()
    srs.ImportFromWkt(proj)
    lyr = mem_src.CreateLayer("z", srs, ogr.wkbPolygon)
    defn = lyr.GetLayerDefn()
    ofeat = ogr.Feature(defn)
    ofeat.SetGeometry(ogr.CreateGeometryFromJson(json.dumps(feat["geometry"])))
    lyr.CreateFeature(ofeat)

    # Rasterize zone polygon
    zone_ds = gdal.GetDriverByName("MEM").Create("", cols, rows, 1, gdal.GDT_Byte)
    zone_ds.SetGeoTransform(gt)
    zone_ds.SetProjection(proj)
    zone_ds.GetRasterBand(1).Fill(0)
    gdal.RasterizeLayer(zone_ds, [1], lyr, burn_values=[1])
    zmask = zone_ds.GetRasterBand(1).ReadAsArray().astype(bool)

    total = int(zmask.sum())
    contam = int((zmask & (cloud_mask == 1)).sum())
    clear_z = zmask & (cloud_mask == 0)
    clear_cnt = int(clear_z.sum())

    mean_lst_val = float(lst[clear_z].mean()) if clear_cnt else None
    mean_ndvi_val = float(ndvi[clear_z].mean()) if clear_cnt else None
    cloud_frac = contam / total if total else 0.0
    mean_slope_val = float(slope[zmask].mean())

    # LST percentiles (cloud-excluded)
    if clear_cnt > 0:
        clear_lst = lst[clear_z]
        lst_p10 = float(np.percentile(clear_lst, 10))
        lst_p50 = float(np.percentile(clear_lst, 50))
        lst_p90 = float(np.percentile(clear_lst, 90))
    else:
        lst_p10 = lst_p50 = lst_p90 = None

    zonal_stats[zname] = {
        "mean_lst": mean_lst_val,
        "mean_ndvi": mean_ndvi_val,
        "cloud_fraction": cloud_frac,
        "mean_slope": mean_slope_val,
        "clear_pixel_count": clear_cnt,
        "total_pixel_count": total,
        "lst_p10": lst_p10,
        "lst_p50": lst_p50,
        "lst_p90": lst_p90,
    }
    zone_ds = None
    mem_src = None

with open(f"{OUTPUT_DIR}/zonal_stats.json", "w") as fh:
    json.dump(zonal_stats, fh, indent=2)

print("[5/5] zonal_stats.json")
for z, s in zonal_stats.items():
    print(f"  {z}: LST={s['mean_lst']:.1f}K  NDVI={s['mean_ndvi']:.3f}  "
          f"cloud={s['cloud_fraction']:.3f}  slope={s['mean_slope']:.2f}°  "
          f"clear={s['clear_pixel_count']}/{s['total_pixel_count']}  "
          f"p10={s['lst_p10']:.1f} p50={s['lst_p50']:.1f} p90={s['lst_p90']:.1f}")
