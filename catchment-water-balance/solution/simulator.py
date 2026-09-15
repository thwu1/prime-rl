#!/usr/bin/env python3

"""Physically-based event hydrology simulator with GDAL geospatial output.

Reads ESRI ASCII Grid rasters, INI configuration, and CSV parameter tables.
Produces CSV summaries, GeoTIFF spatial outputs, and GeoJSON flood extent.
"""

import configparser
import csv
import math
import os
import struct

from osgeo import gdal, ogr, osr


# ── I/O helpers ───────────────────────────────────────────────────────────

def read_asc(path):
    """Read ESRI ASCII Grid file. Returns (header_dict, 2D_data_list)."""
    header = {}
    with open(path) as f:
        for _ in range(6):
            parts = f.readline().strip().split(None, 1)
            key = parts[0].lower()
            val = parts[1]
            if key in ("ncols", "nrows"):
                header[key] = int(val)
            elif key == "nodata_value":
                header["nodata_value"] = float(val)
            else:
                header[key] = float(val)
        data = []
        for _ in range(header["nrows"]):
            row = list(map(float, f.readline().strip().split()))
            data.append(row)
    return header, data


def read_params_csv(path):
    """Read parameter lookup table. Returns dict mapping int type-ID to params."""
    params = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            tid = int(row["type"])
            params[tid] = {k: float(v) for k, v in row.items() if k != "type"}
    return params


def read_rainfall(path):
    """Read rainfall hyetograph CSV."""
    times, intensities = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            times.append(float(row["time_min"]))
            intensities.append(float(row["intensity_mm_h"]))
    return times, intensities


def read_config(path):
    """Read INI configuration file."""
    config = configparser.ConfigParser()
    config.read(path)
    return config


def interp_rainfall(t_min, times, intensities):
    """Linearly interpolate rainfall intensity at time t_min."""
    if t_min <= times[0]:
        return intensities[0]
    if t_min >= times[-1]:
        return intensities[-1]
    for k in range(len(times) - 1):
        if times[k] <= t_min <= times[k + 1]:
            frac = (t_min - times[k]) / (times[k + 1] - times[k])
            return intensities[k] + frac * (intensities[k + 1] - intensities[k])
    return 0.0


def write_geotiff(path, data_2d, nrows, ncols, geotransform, srs_wkt,
                   nodata=-9999, gdal_type=gdal.GDT_Float32):
    """Write a single-band GeoTIFF using GDAL."""
    fmt_map = {
        gdal.GDT_Float32: 'f',
        gdal.GDT_Int16: 'h',
        gdal.GDT_Int32: 'i',
    }
    fmt = fmt_map[gdal_type]
    cast_fn = float if gdal_type == gdal.GDT_Float32 else int

    driver = gdal.GetDriverByName('GTiff')
    ds = driver.Create(path, ncols, nrows, 1, gdal_type)
    ds.SetGeoTransform(geotransform)
    ds.SetProjection(srs_wkt)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(float(nodata))

    for i in range(nrows):
        row_buf = struct.pack(fmt * ncols, *[cast_fn(v) for v in data_2d[i]])
        band.WriteRaster(0, i, ncols, 1, row_buf)

    band.FlushCache()
    ds = None


def create_flood_geojson(maxdepth_data, nrows, ncols, geotransform, srs_wkt,
                          output_path, threshold=0.001):
    """Vectorize flood extent and write as GeoJSON in WGS84."""
    # Create in-memory binary mask raster
    mem_drv = gdal.GetDriverByName('MEM')
    mask_ds = mem_drv.Create('', ncols, nrows, 1, gdal.GDT_Byte)
    mask_ds.SetGeoTransform(geotransform)
    mask_ds.SetProjection(srs_wkt)
    mask_band = mask_ds.GetRasterBand(1)

    for i in range(nrows):
        row_vals = [1 if maxdepth_data[i][j] > threshold else 0
                    for j in range(ncols)]
        buf = struct.pack('B' * ncols, *row_vals)
        mask_band.WriteRaster(0, i, ncols, 1, buf)
    mask_band.FlushCache()

    # Source CRS from the raster's projection
    src_srs = osr.SpatialReference()
    src_srs.ImportFromWkt(srs_wkt)
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    # Polygonize mask into in-memory vector layer
    mem_vec_drv = ogr.GetDriverByName('Memory')
    mem_ds = mem_vec_drv.CreateDataSource('')
    mem_lyr = mem_ds.CreateLayer('mask', src_srs, ogr.wkbPolygon)
    fd = ogr.FieldDefn('gridcode', ogr.OFTInteger)
    mem_lyr.CreateField(fd)

    # Use mask as both source and mask band: only non-zero pixels included
    gdal.Polygonize(mask_band, mask_band, mem_lyr, 0)

    # Destination CRS (WGS84)
    dst_srs = osr.SpatialReference()
    dst_srs.ImportFromEPSG(4326)
    dst_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    coord_transform = osr.CoordinateTransformation(src_srs, dst_srs)

    # Write reprojected polygons as GeoJSON
    if os.path.exists(output_path):
        os.remove(output_path)
    geojson_drv = ogr.GetDriverByName('GeoJSON')
    geojson_ds = geojson_drv.CreateDataSource(output_path)
    geojson_lyr = geojson_ds.CreateLayer('flood_extent', dst_srs, ogr.wkbPolygon)
    gc_fd = ogr.FieldDefn('gridcode', ogr.OFTInteger)
    geojson_lyr.CreateField(gc_fd)

    mem_lyr.ResetReading()
    feat = mem_lyr.GetNextFeature()
    while feat is not None:
        gc = feat.GetField('gridcode')
        if gc > 0:
            geom = feat.GetGeometryRef().Clone()
            geom.Transform(coord_transform)
            out_feat = ogr.Feature(geojson_lyr.GetLayerDefn())
            out_feat.SetGeometry(geom)
            out_feat.SetField('gridcode', 1)
            geojson_lyr.CreateFeature(out_feat)
        feat = mem_lyr.GetNextFeature()

    geojson_ds.Destroy()
    mem_ds = None
    mask_ds = None


# ── Flow direction and slopes ─────────────────────────────────────────────

DIR_OFFSETS = {
    7: (-1, -1), 8: (-1, 0), 9: (-1, 1),
    4: (0, -1),              6: (0, 1),
    1: (1, -1),  2: (1, 0),  3: (1, 1),
}


def compute_ldd(dem, nrows, ncols, cellsize):
    """Derive D8 local drain direction from DEM."""
    diag = cellsize * math.sqrt(2.0)
    dir_dists = {}
    for d, (di, dj) in DIR_OFFSETS.items():
        dir_dists[d] = diag if (abs(di) + abs(dj) == 2) else cellsize

    ldd = [[5] * ncols for _ in range(nrows)]

    for i in range(nrows):
        for j in range(ncols):
            max_slope = 0.0
            best_dir = 5
            for d, (di, dj) in DIR_OFFSETS.items():
                ni, nj = i + di, j + dj
                if 0 <= ni < nrows and 0 <= nj < ncols:
                    drop = dem[i][j] - dem[ni][nj]
                    if drop > 0:
                        slope = drop / dir_dists[d]
                        if slope > max_slope:
                            max_slope = slope
                            best_dir = d
            ldd[i][j] = best_dir
    return ldd


def compute_slopes(dem, ldd, nrows, ncols, cellsize):
    """Compute slope in flow direction for each cell."""
    diag = cellsize * math.sqrt(2.0)
    slopes = [[0.001] * ncols for _ in range(nrows)]

    for i in range(nrows):
        for j in range(ncols):
            d = ldd[i][j]
            if d == 5:
                best = 0.001
                for dd, (di, dj) in DIR_OFFSETS.items():
                    ni, nj = i + di, j + dj
                    if 0 <= ni < nrows and 0 <= nj < ncols:
                        if dem[ni][nj] > dem[i][j]:
                            dist = diag if (abs(di) + abs(dj) == 2) else cellsize
                            s = (dem[ni][nj] - dem[i][j]) / dist
                            best = max(best, s)
                slopes[i][j] = best
            else:
                di, dj = DIR_OFFSETS[d]
                ni, nj = i + di, j + dj
                dist = diag if (abs(di) + abs(dj) == 2) else cellsize
                drop = dem[i][j] - dem[ni][nj]
                slopes[i][j] = max(drop / dist, 0.001)
    return slopes


def get_processing_order(dem, nrows, ncols):
    """Return cells sorted from highest to lowest elevation."""
    cells = [(dem[i][j], i, j) for i in range(nrows) for j in range(ncols)]
    cells.sort(reverse=True)
    return [(i, j) for _, i, j in cells]


def get_downstream(i, j, ldd, nrows, ncols):
    """Return downstream cell coordinates, or None for outlet."""
    d = ldd[i][j]
    if d == 5:
        return None
    di, dj = DIR_OFFSETS[d]
    ni, nj = i + di, j + dj
    if 0 <= ni < nrows and 0 <= nj < ncols:
        return (ni, nj)
    return None


def compute_flow_accumulation(ldd, nrows, ncols, order):
    """Compute flow accumulation: upstream cell count including self."""
    acc = [[1] * ncols for _ in range(nrows)]
    for i, j in order:  # highest to lowest
        d = ldd[i][j]
        if d == 5:
            continue
        if d in DIR_OFFSETS:
            di, dj = DIR_OFFSETS[d]
            ni, nj = i + di, j + dj
            if 0 <= ni < nrows and 0 <= nj < ncols:
                acc[ni][nj] += acc[i][j]
    return acc


# ── Green-Ampt infiltration ──────────────────────────────────────────────

def green_ampt_potential(ksat, psi_dtheta, F0, dt_hr):
    """Return potential additional infiltration (mm) via Newton-Raphson."""
    if F0 < 1e-10:
        return 1e6  # capacity essentially infinite at F~0

    target = ksat * dt_hr
    F = F0 + target  # initial guess

    for _ in range(80):
        if F <= F0:
            F = F0 + 1e-8
        ln_arg = (F + psi_dtheta) / (F0 + psi_dtheta)
        if ln_arg <= 0:
            break
        g = F - F0 - target - psi_dtheta * math.log(ln_arg)
        gp = 1.0 - psi_dtheta / (F + psi_dtheta)
        if abs(gp) < 1e-15:
            break
        F_new = F - g / gp
        if F_new <= F0:
            F_new = (F + F0) / 2.0
        if abs(F_new - F) < 1e-10:
            return max(0.0, F_new - F0)
        F = F_new

    return max(0.0, F - F0)


# ── Main simulation ──────────────────────────────────────────────────────

def run_simulation(config_path):
    config = read_config(config_path)

    base_dir = os.path.dirname(os.path.abspath(config_path))

    # Simulation parameters
    dt_s = float(config["simulation"]["timestep_s"])
    duration_min = float(config["simulation"]["duration_min"])
    dt_hr = dt_s / 3600.0
    dt_min = dt_s / 60.0

    # Input file paths
    dem_path = os.path.join(base_dir, config["input"]["dem"])
    soiltype_path = os.path.join(base_dir, config["input"]["soiltype"])
    landcover_path = os.path.join(base_dir, config["input"]["landcover"])
    soil_params_path = os.path.join(base_dir, config["input"]["soil_params"])
    lc_params_path = os.path.join(base_dir, config["input"]["landcover_params"])
    rainfall_path = os.path.join(base_dir, config["input"]["rainfall"])
    output_dir = os.path.join(base_dir, config["output"]["directory"])

    # CRS from config
    crs_str = config["spatial"]["crs"]
    epsg_code = int(crs_str.split(":")[1])
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg_code)
    srs_wkt = srs.ExportToWkt()

    # Read rasters
    dem_header, dem = read_asc(dem_path)
    _, soiltype = read_asc(soiltype_path)
    _, landcover = read_asc(landcover_path)

    nrows = dem_header["nrows"]
    ncols = dem_header["ncols"]
    cellsize = dem_header["cellsize"]
    xllcorner = dem_header["xllcorner"]
    yllcorner = dem_header["yllcorner"]

    # Compute geotransform: (x_topleft, pixel_w, rot, y_topleft, rot, -pixel_h)
    geotransform = (xllcorner, cellsize, 0.0,
                    yllcorner + nrows * cellsize, 0.0, -cellsize)

    # Read parameter tables
    soil_params = read_params_csv(soil_params_path)
    lc_params = read_params_csv(lc_params_path)
    rain_t, rain_i = read_rainfall(rainfall_path)

    cell_area = cellsize * cellsize
    total_cells = nrows * ncols
    catch_area = total_cells * cell_area

    # Build per-cell parameter arrays from spatial rasters + lookup tables
    ksat = [[0.0] * ncols for _ in range(nrows)]
    psi_dtheta = [[0.0] * ncols for _ in range(nrows)]
    max_infil = [[0.0] * ncols for _ in range(nrows)]
    mann_n = [[0.0] * ncols for _ in range(nrows)]
    veg_cover = [[0.0] * ncols for _ in range(nrows)]
    smax_arr = [[0.0] * ncols for _ in range(nrows)]

    for i in range(nrows):
        for j in range(ncols):
            st = int(soiltype[i][j])
            sp = soil_params[st]
            ksat[i][j] = sp["ksat_mm_hr"]
            dtheta = sp["porosity"] - sp["initial_moisture"]
            psi_dtheta[i][j] = sp["suction_mm"] * dtheta
            max_infil[i][j] = sp["depth_mm"] * dtheta

            lc = int(landcover[i][j])
            lp = lc_params[lc]
            mann_n[i][j] = lp["manning_n"]
            veg_cover[i][j] = lp["vegetation_cover"]
            smax_arr[i][j] = lp["canopy_storage_mm"]

    # Derived grids
    ldd = compute_ldd(dem, nrows, ncols, cellsize)
    slopes = compute_slopes(dem, ldd, nrows, ncols, cellsize)
    order = get_processing_order(dem, nrows, ncols)
    flow_acc = compute_flow_accumulation(ldd, nrows, ncols, order)

    # State arrays
    cum_rain = [[0.0] * ncols for _ in range(nrows)]
    interc = [[0.0] * ncols for _ in range(nrows)]
    cum_infil = [[0.0] * ncols for _ in range(nrows)]
    wdepth = [[0.0] * ncols for _ in range(nrows)]  # metres
    max_depth = [[0.0] * ncols for _ in range(nrows)]

    # Volume accumulators (m3)
    tot_rain_v = 0.0
    tot_interc_v = 0.0
    tot_infil_v = 0.0
    tot_out_v = 0.0

    peak_q = 0.0
    peak_t = 0.0

    ts_out = []
    hyd_out = []

    n_steps = int(duration_min / dt_min)

    for step in range(n_steps):
        t_min = step * dt_min
        rain_rate = interp_rainfall(t_min, rain_t, rain_i)  # mm/hr
        rain_mm = rain_rate * dt_hr  # mm this step

        step_rain_v = 0.0
        step_interc_v = 0.0
        step_infil_v = 0.0

        # ── per-cell: rain, interception, infiltration ──
        for i in range(nrows):
            for j in range(ncols):
                # Gross rainfall
                cum_rain[i][j] += rain_mm
                step_rain_v += rain_mm * cell_area / 1000.0

                # Interception (exponential saturation)
                old_I = interc[i][j]
                s = smax_arr[i][j]
                if s > 0 and cum_rain[i][j] > 0:
                    new_I = s * (1.0 - math.exp(
                        -veg_cover[i][j] * cum_rain[i][j] / s))
                else:
                    new_I = 0.0
                dI = min(max(0.0, new_I - old_I), rain_mm)
                interc[i][j] = old_I + dI
                step_interc_v += dI * cell_area / 1000.0

                net_mm = rain_mm - dI

                # Available water on surface (mm)
                avail_mm = net_mm + wdepth[i][j] * 1000.0

                if avail_mm < 1e-12:
                    continue

                F = cum_infil[i][j]

                # Potential infiltration
                pot = green_ampt_potential(
                    ksat[i][j], psi_dtheta[i][j], F, dt_hr)

                # Actual infiltration
                act = min(pot, avail_mm, max(0.0, max_infil[i][j] - F))
                act = max(0.0, act)

                cum_infil[i][j] += act
                step_infil_v += act * cell_area / 1000.0
                wdepth[i][j] = max(0.0, (avail_mm - act) / 1000.0)

        # ── routing (upstream -> downstream) ──
        step_out_v = 0.0
        for ci, cj in order:
            h = wdepth[ci][cj]
            if h < 1e-12:
                continue
            S = slopes[ci][cj]
            n = mann_n[ci][cj]
            # Manning unit-width: q = (1/n) h^{5/3} S^{1/2}  [m2/s]
            q = (1.0 / n) * (h ** (5.0 / 3.0)) * math.sqrt(S)
            vol_out = q * cellsize * dt_s
            avail_vol = h * cell_area
            vol_out = min(vol_out, avail_vol)

            wdepth[ci][cj] -= vol_out / cell_area
            if wdepth[ci][cj] < 0:
                wdepth[ci][cj] = 0.0

            ds = get_downstream(ci, cj, ldd, nrows, ncols)
            if ds is not None:
                wdepth[ds[0]][ds[1]] += vol_out / cell_area
            else:
                step_out_v += vol_out

        # Track max depth per cell
        for i in range(nrows):
            for j in range(ncols):
                if wdepth[i][j] > max_depth[i][j]:
                    max_depth[i][j] = wdepth[i][j]

        # ── accumulate totals ──
        tot_rain_v += step_rain_v
        tot_interc_v += step_interc_v
        tot_infil_v += step_infil_v
        tot_out_v += step_out_v

        # ── catchment-average mm ──
        rain_mm_cum = tot_rain_v / catch_area * 1000.0
        interc_mm_cum = tot_interc_v / catch_area * 1000.0
        infil_mm_cum = tot_infil_v / catch_area * 1000.0
        out_mm_cum = tot_out_v / catch_area * 1000.0

        surf_v = 0.0
        for ii in range(nrows):
            for jj in range(ncols):
                surf_v += wdepth[ii][jj] * cell_area
        surf_mm = surf_v / catch_area * 1000.0

        mb = 0.0
        if rain_mm_cum > 0:
            mb = (
                (rain_mm_cum - interc_mm_cum - infil_mm_cum
                 - surf_mm - out_mm_cum)
                / rain_mm_cum
                * 100.0
            )

        Q = step_out_v / dt_s  # m3/s
        if Q > peak_q:
            peak_q = Q
            peak_t = t_min

        ts_out.append(
            (t_min, rain_mm_cum, interc_mm_cum, infil_mm_cum,
             surf_mm, out_mm_cum, mb)
        )
        hyd_out.append((t_min, Q))

    # ── final stats ──
    rain_final = ts_out[-1][1] if ts_out else 0.0
    rc = out_mm_cum / rain_final if rain_final > 0 else 0.0
    mb_final = ts_out[-1][6] if ts_out else 0.0

    # ── write CSV outputs ──
    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "totals.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["variable", "value"])
        w.writerow(["total_rainfall_mm", f"{rain_final:.6f}"])
        w.writerow(["total_interception_mm", f"{interc_mm_cum:.6f}"])
        w.writerow(["total_infiltration_mm", f"{infil_mm_cum:.6f}"])
        w.writerow(["total_outflow_mm", f"{out_mm_cum:.6f}"])
        w.writerow(["peak_discharge_m3s", f"{peak_q:.6f}"])
        w.writerow(["peak_time_min", f"{peak_t:.2f}"])
        w.writerow(["mass_balance_error_pct", f"{mb_final:.6f}"])
        w.writerow(["runoff_coefficient", f"{rc:.6f}"])

    with open(os.path.join(output_dir, "totalseries.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "time_min", "rainfall_mm", "interception_mm", "infiltration_mm",
            "surface_storage_mm", "outflow_mm", "mass_balance_error_pct",
        ])
        for rec in ts_out:
            w.writerow([f"{v:.6f}" for v in rec])

    with open(os.path.join(output_dir, "hydrograph.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_min", "discharge_m3s"])
        for t, q in hyd_out:
            w.writerow([f"{t:.2f}", f"{q:.6f}"])

    # ── write GeoTIFF spatial outputs ──
    write_geotiff(
        os.path.join(output_dir, "flowdir.tif"),
        ldd, nrows, ncols, geotransform, srs_wkt,
        nodata=-9999, gdal_type=gdal.GDT_Int16,
    )

    write_geotiff(
        os.path.join(output_dir, "flowacc.tif"),
        flow_acc, nrows, ncols, geotransform, srs_wkt,
        nodata=-9999, gdal_type=gdal.GDT_Int32,
    )

    write_geotiff(
        os.path.join(output_dir, "maxdepth.tif"),
        max_depth, nrows, ncols, geotransform, srs_wkt,
        nodata=-9999, gdal_type=gdal.GDT_Float32,
    )

    # ── create flood extent GeoJSON ──
    create_flood_geojson(
        max_depth, nrows, ncols, geotransform, srs_wkt,
        os.path.join(output_dir, "flood_extent.geojson"),
        threshold=0.001,
    )
