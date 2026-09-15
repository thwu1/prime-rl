#!/usr/bin/env python3
"""Generate synthetic geospatial criterion layers for solar farm suitability analysis."""
import numpy as np
from osgeo import gdal, osr
import os

WIDTH = 400
HEIGHT = 400
PIXEL_SIZE = 30.0
ORIGIN_X = 500000.0
ORIGIN_Y = 5012000.0
EPSG = 32617


def write_geotiff(filepath, data, nodata=-9999):
    driver = gdal.GetDriverByName("GTiff")
    if data.ndim == 2:
        data = data[np.newaxis, :, :]
    nbands = data.shape[0]
    ds = driver.Create(filepath, WIDTH, HEIGHT, nbands, gdal.GDT_Float32)
    ds.SetGeoTransform((ORIGIN_X, PIXEL_SIZE, 0, ORIGIN_Y, 0, -PIXEL_SIZE))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(EPSG)
    ds.SetProjection(srs.ExportToWkt())
    for b in range(nbands):
        band = ds.GetRasterBand(b + 1)
        band.WriteArray(data[b].astype(np.float32))
        band.SetNoDataValue(float(nodata))
    ds.FlushCache()
    ds = None


def main():
    rng = np.random.RandomState(42)
    os.makedirs("/app/data", exist_ok=True)

    yy, xx = np.mgrid[:HEIGHT, :WIDTH]
    yyf = yy.astype(np.float64)
    xxf = xx.astype(np.float64)

    nodata_mask = np.zeros((HEIGHT, WIDTH), dtype=bool)
    nodata_mask[:, 380:] = True

    # Slope (degrees, mostly 2-10 range)
    slope_clean = 2.0 + 5.0 * (yyf / HEIGHT) + 3.0 * np.sin(
        xxf * np.pi / 100
    ) * np.sin(yyf * np.pi / 80)
    slope = slope_clean + rng.normal(0, 0.5, (HEIGHT, WIDTH))
    slope = np.clip(slope, 0, 30).astype(np.float32)
    slope[nodata_mask] = -9999
    write_geotiff("/app/data/slope.tif", slope)

    # Aspect (degrees, 0-360, centered around 180)
    aspect = 180.0 + 50.0 * np.sin(xxf * np.pi / 120) + 30.0 * np.cos(
        yyf * np.pi / 100
    )
    aspect += rng.normal(0, 10, (HEIGHT, WIDTH))
    aspect = (aspect % 360).astype(np.float32)
    aspect[nodata_mask] = -9999
    write_geotiff("/app/data/aspect.tif", aspect)

    # Road distance (meters): horizontal road at row=200, vertical at col=250
    road_h = np.abs(yyf - 200) * PIXEL_SIZE
    road_v = np.abs(xxf - 250) * PIXEL_SIZE
    road_dist = np.minimum(road_h, road_v).astype(np.float32)
    road_dist[nodata_mask] = -9999
    write_geotiff("/app/data/road_distance.tif", road_dist)

    # Land cover (categorical: 1=Forest,2=Grassland,3=Cropland,4=Barren,5=Urban,6=Water)
    landcover = np.full((HEIGHT, WIDTH), 3, dtype=np.float32)
    landcover[:200, :190] = 1
    landcover[150:250, 190:320] = 2
    landcover[300:, 200:380] = 4
    landcover[50:120, 230:340] = 5
    water_mask = ((xxf - 100) ** 2 + (yyf - 350) ** 2) <= 35 ** 2
    landcover[water_mask] = 6
    landcover[nodata_mask] = 0
    write_geotiff("/app/data/landcover.tif", landcover, nodata=0)

    # Solar irradiance (kWh/m2/day, 4.5-6.5 range)
    irradiance = 4.5 + 2.0 * (yyf / HEIGHT) - 0.03 * np.clip(slope_clean, 0, 30)
    irradiance += rng.normal(0, 0.15, (HEIGHT, WIDTH))
    irradiance = np.clip(irradiance, 3, 7).astype(np.float32)
    irradiance[nodata_mask] = -9999
    write_geotiff("/app/data/irradiance.tif", irradiance)

    # Protected areas (binary: 1=protected)
    protected = np.zeros((HEIGHT, WIDTH), dtype=np.float32)
    protected[160:240, 160:260] = 1
    protected[20:80, 20:80] = 1
    protected[nodata_mask] = 255
    write_geotiff("/app/data/protected.tif", protected, nodata=255)

    # Flood zone (binary: 1=flood-prone, around water body)
    flood = np.zeros((HEIGHT, WIDTH), dtype=np.float32)
    flood_mask = ((xxf - 100) ** 2 + (yyf - 350) ** 2) <= 55 ** 2
    flood[flood_mask] = 1
    flood[nodata_mask] = 255
    write_geotiff("/app/data/flood_zone.tif", flood, nodata=255)

    print("Generated criterion layers at /app/data/")


if __name__ == "__main__":
    main()
