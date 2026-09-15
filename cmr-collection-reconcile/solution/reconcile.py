#!/usr/bin/env python3

"""Geospatial Raster-STAC Metadata Reconciliation Tool.

Inspects GeoTIFF raster files using GDAL, transforms spatial extents to
WGS84 via osr.CoordinateTransformation, and cross-validates against STAC
Item metadata to detect discrepancies in bounding boxes, CRS identifiers,
temporal bounds, and band counts.
"""

import json
import os
import glob
from osgeo import gdal, osr


BBOX_TOLERANCE_DEG = 0.5


def get_raster_info(filepath):
    """Extract CRS, WGS84 bbox, and band count from a GeoTIFF using GDAL."""
    ds = gdal.Open(filepath)
    if ds is None:
        raise ValueError(f"Cannot open {filepath}")

    gt = ds.GetGeoTransform()
    w, h = ds.RasterXSize, ds.RasterYSize
    band_count = ds.RasterCount

    ulx, uly = gt[0], gt[3]
    lrx = ulx + w * gt[1]
    lry = uly + h * gt[5]

    src_srs = osr.SpatialReference()
    src_srs.ImportFromWkt(ds.GetProjection())
    src_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    # Try to identify EPSG code
    src_srs.AutoIdentifyEPSG()
    epsg = src_srs.GetAuthorityCode(None)
    epsg = int(epsg) if epsg else None

    # Transform extent to WGS84
    tgt_srs = osr.SpatialReference()
    tgt_srs.ImportFromEPSG(4326)
    tgt_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    ct = osr.CoordinateTransformation(src_srs, tgt_srs)

    # Sample corners and edge midpoints for accurate envelope
    points = [
        (ulx, uly), (lrx, uly), (lrx, lry), (ulx, lry),
        ((ulx + lrx) / 2, uly), ((ulx + lrx) / 2, lry),
        (ulx, (uly + lry) / 2), (lrx, (uly + lry) / 2),
    ]

    lons, lats = [], []
    for x, y in points:
        lon, lat, _ = ct.TransformPoint(x, y)
        lons.append(lon)
        lats.append(lat)

    bbox_wgs84 = [
        round(min(lons), 6), round(min(lats), 6),
        round(max(lons), 6), round(max(lats), 6),
    ]

    ds = None
    return {
        'bbox_wgs84': bbox_wgs84,
        'epsg': epsg,
        'band_count': band_count,
    }


def check_bbox(stac_bbox, file_bbox, tol=BBOX_TOLERANCE_DEG):
    """Compare STAC bbox against file-derived WGS84 bbox."""
    if not isinstance(stac_bbox, list) or len(stac_bbox) != 4:
        return False, "Invalid bbox format"

    # Obvious error: values in projected CRS, not geographic degrees
    if any(abs(v) > 180 for v in stac_bbox):
        return False, (
            "STAC bbox contains values outside the [-180, 180] degree range, "
            "indicating projected CRS coordinates were used instead of WGS84"
        )

    # Compare each coordinate within tolerance
    labels = ['west', 'south', 'east', 'north']
    for i, (s, f) in enumerate(zip(stac_bbox, file_bbox)):
        if abs(s - f) > tol:
            return False, (
                f"Bbox {labels[i]} differs: "
                f"STAC={s:.6f}, file-derived={f:.6f} (delta={abs(s - f):.3f} deg)"
            )

    return True, "OK"


def main():
    raster_dir = '/app/rasters'
    stac_dir = '/app/stac_items'
    output_path = '/app/output/reconciliation.json'

    os.makedirs('/app/output', exist_ok=True)

    errors = []
    files_analyzed = []

    stac_files = sorted(glob.glob(os.path.join(stac_dir, '*.json')))

    for stac_path in stac_files:
        with open(stac_path) as f:
            item = json.load(f)

        file_id = os.path.splitext(os.path.basename(stac_path))[0]
        raster_path = os.path.join(raster_dir, f'{file_id}.tif')

        if not os.path.exists(raster_path):
            continue

        files_analyzed.append(file_id)
        info = get_raster_info(raster_path)
        props = item.get('properties', {})

        # ── CRS check ────────────────────────────────────────────────────
        stac_epsg = props.get('proj:epsg')
        file_epsg = info['epsg']
        if (stac_epsg is not None and file_epsg is not None
                and stac_epsg != file_epsg):
            errors.append({
                'file_id': file_id,
                'error_type': 'crs_mismatch',
                'field': 'properties.proj:epsg',
                'stac_value': stac_epsg,
                'file_value': file_epsg,
                'severity': 'critical',
                'description': (
                    f'STAC proj:epsg is {stac_epsg} but raster file CRS '
                    f'is EPSG:{file_epsg}'
                ),
            })

        # ── Spatial extent check ─────────────────────────────────────────
        stac_bbox = item.get('bbox', [])
        file_bbox = info['bbox_wgs84']
        bbox_ok, bbox_msg = check_bbox(stac_bbox, file_bbox)
        if not bbox_ok:
            errors.append({
                'file_id': file_id,
                'error_type': 'spatial_extent',
                'field': 'bbox',
                'stac_value': stac_bbox,
                'file_value': file_bbox,
                'severity': 'critical',
                'description': bbox_msg,
            })

        # ── Temporal check ───────────────────────────────────────────────
        start = props.get('start_datetime')
        end = props.get('end_datetime')
        if start and end and start > end:
            errors.append({
                'file_id': file_id,
                'error_type': 'temporal_extent',
                'field': 'properties.start_datetime / end_datetime',
                'stac_value': {'start_datetime': start, 'end_datetime': end},
                'file_value': 'start_datetime must precede end_datetime',
                'severity': 'major',
                'description': (
                    f'start_datetime ({start}) is after '
                    f'end_datetime ({end})'
                ),
            })

        # ── Band count check ─────────────────────────────────────────────
        stac_bands = props.get('eo:bands', [])
        file_bands = info['band_count']
        if len(stac_bands) != file_bands:
            errors.append({
                'file_id': file_id,
                'error_type': 'band_count',
                'field': 'properties.eo:bands',
                'stac_value': len(stac_bands),
                'file_value': file_bands,
                'severity': 'major',
                'description': (
                    f'STAC eo:bands lists {len(stac_bands)} bands but '
                    f'raster file has {file_bands}'
                ),
            })

    # ── Build report ─────────────────────────────────────────────────────
    critical = sum(1 for e in errors if e['severity'] == 'critical')
    major = sum(1 for e in errors if e['severity'] == 'major')

    report = {
        'files_analyzed': files_analyzed,
        'errors': errors,
        'summary': {
            'total_files': len(files_analyzed),
            'total_errors': len(errors),
            'critical_count': critical,
            'major_count': major,
        },
    }

    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Reconciliation complete: {len(errors)} errors across "
          f"{len(files_analyzed)} files")


if __name__ == '__main__':
    main()
