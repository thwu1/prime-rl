#!/usr/bin/env python3
"""OGC API - Features Part 1: Core server implementation."""

from flask import Flask, request, jsonify, Response, abort
import json
import os
from datetime import datetime, timezone
from dateutil.parser import isoparse

app = Flask(__name__)

DATA_DIR = '/app/data'

KNOWN_PARAMS = {'bbox', 'limit', 'datetime', 'offset', 'f'}


def load_data():
    """Load GeoJSON feature collections from data directory."""
    collections = {}
    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.endswith('.geojson'):
            coll_id = fname.replace('.geojson', '')
            with open(os.path.join(DATA_DIR, fname)) as f:
                collections[coll_id] = json.load(f)
    return collections


COLLECTIONS = None


def get_collections():
    global COLLECTIONS
    if COLLECTIONS is None:
        COLLECTIONS = load_data()
    return COLLECTIONS


def get_base_url():
    return request.url_root.rstrip('/')


def extract_coords(geometry):
    """Extract all [lon, lat] coordinate pairs from a GeoJSON geometry."""
    gtype = geometry.get('type', '')
    coords = geometry.get('coordinates', [])
    if gtype == 'Point':
        return [coords[:2]]
    elif gtype in ('MultiPoint', 'LineString'):
        return [c[:2] for c in coords]
    elif gtype in ('MultiLineString', 'Polygon'):
        result = []
        for ring in coords:
            result.extend(c[:2] for c in ring)
        return result
    elif gtype == 'MultiPolygon':
        result = []
        for poly in coords:
            for ring in poly:
                result.extend(c[:2] for c in ring)
        return result
    return []


def compute_extent(features):
    """Compute spatial and temporal extent from a list of features."""
    if not features:
        return {}
    min_lon, min_lat = 180, 90
    max_lon, max_lat = -180, -90
    min_time, max_time = None, None
    for f in features:
        geom = f.get('geometry')
        if geom:
            for lon, lat in extract_coords(geom):
                min_lon = min(min_lon, lon)
                max_lon = max(max_lon, lon)
                min_lat = min(min_lat, lat)
                max_lat = max(max_lat, lat)
        dt = f.get('properties', {}).get('datetime')
        if dt:
            if min_time is None or dt < min_time:
                min_time = dt
            if max_time is None or dt > max_time:
                max_time = dt
    extent = {
        "spatial": {
            "bbox": [[min_lon, min_lat, max_lon, max_lat]],
            "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
        }
    }
    if min_time and max_time:
        extent["temporal"] = {
            "interval": [[min_time, max_time]],
            "trs": "http://www.opengis.net/def/uom/ISO-8601/0/Gregorian"
        }
    return extent


def bbox_intersects(geometry, bbox):
    """Check if a geometry intersects with a bounding box."""
    if geometry is None:
        return True
    min_lat, min_lon, max_lat, max_lon = bbox[0], bbox[1], bbox[2], bbox[3]
    for lon, lat in extract_coords(geometry):
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            return True
    return False


def datetime_intersects(properties, datetime_param):
    """Check if a feature's datetime intersects with a datetime filter."""
    dt = properties.get('datetime')
    if dt is None:
        return True
    try:
        feature_dt = isoparse(dt)
    except (ValueError, TypeError):
        return True
    if '/' in datetime_param:
        parts = datetime_param.split('/')
        start_str, end_str = parts[0], parts[1]
        start = isoparse(start_str)
        end = isoparse(end_str)
        return start <= feature_dt <= end
    else:
        filter_dt = isoparse(datetime_param)
        if len(datetime_param) <= 10:
            return feature_dt.date() == filter_dt.date()
        return feature_dt == filter_dt


@app.route('/')
def landing_page():
    base = get_base_url()
    return jsonify({
        "title": "OGC API Features Test Server",
        "description": "Test implementation of OGC API - Features Part 1: Core",
        "links": [
            {
                "href": f"{base}/",
                "rel": "self",
                "type": "application/json",
                "title": "This document"
            },
            {
                "href": f"{base}/api",
                "rel": "service-description",
                "type": "application/vnd.oai.openapi+json;version=3.0",
                "title": "API definition"
            },
            {
                "href": f"{base}/conformance",
                "rel": "compliance",
                "type": "application/json",
                "title": "OGC API conformance classes"
            },
            {
                "href": f"{base}/collections",
                "rel": "data",
                "type": "application/json",
                "title": "Feature collections"
            }
        ]
    })


@app.route('/conformance')
def conformance():
    return jsonify({
        "conformsTo": [
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson"
        ]
    })


@app.route('/api')
def api_definition():
    with open('/app/openapi.yaml') as f:
        content = f.read()
    return Response(content, mimetype='application/vnd.oai.openapi+json;version=3.0')


@app.route('/collections')
def collections_list():
    base = get_base_url()
    colls = get_collections()
    items = []
    for coll_id, data in colls.items():
        features = data.get('features', [])
        extent = compute_extent(features)
        items.append({
            "id": coll_id,
            "title": data.get('name', coll_id),
            "description": data.get('description', ''),
            "links": [
                {"href": f"{base}/collections/{coll_id}", "rel": "self", "type": "application/json"},
                {"href": f"{base}/collections/{coll_id}/items", "rel": "items", "type": "application/geo+json"}
            ],
            "extent": extent,
            "crs": ["EPSG:4326"]
        })
    return jsonify({
        "links": [
            {"href": f"{base}/collections", "rel": "self", "type": "application/json"}
        ],
        "collections": items
    })


@app.route('/collections/<collection_id>')
def collection_detail(collection_id):
    colls = get_collections()
    if collection_id not in colls:
        abort(404)
    base = get_base_url()
    data = colls[collection_id]
    features = data.get('features', [])
    extent = compute_extent(features)
    return jsonify({
        "id": collection_id,
        "title": data.get('name', collection_id),
        "description": data.get('description', ''),
        "links": [
            {"href": f"{base}/collections/{collection_id}", "rel": "self", "type": "application/json"},
            {"href": f"{base}/collections/{collection_id}/items", "rel": "items", "type": "application/geo+json"}
        ],
        "extent": extent,
        "crs": ["EPSG:4326"]
    })


@app.route('/collections/<collection_id>/items')
def collection_items(collection_id):
    colls = get_collections()
    if collection_id not in colls:
        abort(404)
    base = get_base_url()
    data = colls[collection_id]
    all_features = data.get('features', [])

    # Parse limit
    limit_str = request.args.get('limit', '10')
    try:
        limit = int(limit_str)
    except (ValueError, TypeError):
        limit = 10
    limit = max(1, min(limit, 10000))

    # Parse bbox
    bbox = None
    bbox_str = request.args.get('bbox')
    if bbox_str:
        try:
            bbox = [float(x) for x in bbox_str.split(',')]
        except ValueError:
            return jsonify({"code": "InvalidParameterValue", "description": "Invalid bbox format"}), 400

    # Parse datetime
    datetime_param = request.args.get('datetime')

    # Filter features
    filtered = []
    for feature in all_features:
        if bbox and not bbox_intersects(feature.get('geometry'), bbox):
            continue
        if datetime_param and not datetime_intersects(feature.get('properties', {}), datetime_param):
            continue
        filtered.append(feature)

    number_matched = len(filtered)
    number_returned = len(filtered)

    # Pagination
    offset = int(request.args.get('offset', '0'))
    paginated = filtered[offset:offset + limit]

    links = [
        {"href": f"{base}/collections/{collection_id}/items", "rel": "self", "type": "application/geo+json"}
    ]
    next_offset = offset + limit + 1
    if next_offset < number_matched:
        links.append({
            "href": f"{base}/collections/{collection_id}/items?offset={next_offset}&limit={limit}",
            "rel": "next",
            "type": "application/geo+json"
        })

    return jsonify({
        "type": "FeatureCollection",
        "features": paginated,
        "links": links,
        "timeStamp": datetime.now(timezone.utc).isoformat(),
        "numberMatched": number_matched,
        "numberReturned": number_returned
    })


@app.route('/collections/<collection_id>/items/<feature_id>')
def feature_detail(collection_id, feature_id):
    colls = get_collections()
    if collection_id not in colls:
        abort(404)
    base = get_base_url()
    data = colls[collection_id]
    for feature in data.get('features', []):
        fid = feature.get('id', feature.get('properties', {}).get('id'))
        if str(fid) == str(feature_id):
            result = dict(feature)
            result['links'] = [
                {"href": f"{base}/collections/{collection_id}/items/{feature_id}", "rel": "self", "type": "application/geo+json"},
                {"href": f"{base}/collections/{collection_id}", "rel": "collection", "type": "application/json"}
            ]
            return Response(json.dumps(result), mimetype='application/geo+json')
    abort(404)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
