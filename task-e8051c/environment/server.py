#!/usr/bin/env python3
"""OGC API Features Part 1: Core server implementation."""

import json
import os
from datetime import datetime as dt_cls
from flask import Flask, request, jsonify, Response

app = Flask(__name__)

DATA_DIR = "/app/data"
BASE_URL = "http://localhost:5000"

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
collections_data = {}
collection_meta = {}

for _fname in sorted(os.listdir(DATA_DIR)):
    if not _fname.endswith(".geojson"):
        continue
    _cid = _fname[:-8]
    with open(os.path.join(DATA_DIR, _fname)) as _fh:
        _fc = json.load(_fh)
    collections_data[_cid] = _fc["features"]

    _lons, _lats, _times = [], [], []
    for _feat in _fc["features"]:
        _g = _feat.get("geometry")
        if _g and _g.get("type") == "Point":
            _lons.append(_g["coordinates"][0])
            _lats.append(_g["coordinates"][1])
        _dt_val = (_feat.get("properties") or {}).get("datetime")
        if _dt_val:
            _times.append(_dt_val)

    _extent = {}
    if _lons:
        _extent["spatial"] = {
            "bbox": [[min(_lats), min(_lons), max(_lats), max(_lons)]],
            "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        }
    if _times:
        _extent["temporal"] = {
            "interval": [[min(_times), max(_times)]],
            "trs": "http://www.opengis.net/def/uom/ISO-8601/0/Gregorian",
        }
    collection_meta[_cid] = {
        "id": _cid,
        "title": _cid.replace("_", " ").title(),
        "description": f"Collection of {_cid.replace('_', ' ')}",
        "extent": _extent,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_bbox(s):
    parts = s.split(",")
    if len(parts) not in (4, 6):
        return None
    try:
        return [float(x) for x in parts]
    except ValueError:
        return None


def _parse_dt(s):
    """Parse ISO 8601 datetime or interval string."""
    if "/" in s:
        a, b = s.split("/", 1)
        start = dt_cls.fromisoformat(a.replace("Z", "+00:00"))
        end = dt_cls.fromisoformat(b.replace("Z", "+00:00"))
        return start, end
    d = dt_cls.fromisoformat(s.replace("Z", "+00:00"))
    return d, d


def _in_bbox(geom, bbox):
    if not geom or geom.get("type") != "Point":
        return False
    lat, lon = geom["coordinates"][0], geom["coordinates"][1]
    w, s, e, n = bbox[:4]
    if w <= e:
        return w <= lon <= e and s <= lat <= n
    return (lon >= w or lon <= e) and s <= lat <= n


def _in_dt(props, rng):
    ds = (props or {}).get("datetime")
    if not ds:
        return True
    d = dt_cls.fromisoformat(ds.replace("Z", "+00:00"))
    start, end = rng
    if start is not None and d < start:
        return False
    if end is not None and d > end:
        return False
    return True


def _geojson(obj):
    return Response(json.dumps(obj), content_type="application/geo+json")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.route("/")
def landing_page():
    return jsonify({
        "title": "OGC API Features Server",
        "description": "OGC API Features Part 1: Core server",
        "links": [
            {"href": f"{BASE_URL}/", "rel": "self", "type": "application/json",
             "title": "This document"},
            {"href": f"{BASE_URL}/api", "rel": "service-desc",
             "type": "application/json", "title": "API definition"},
            {"href": f"{BASE_URL}/conformance", "rel": "conformance",
             "type": "application/json", "title": "Conformance declaration"},
            {"href": f"{BASE_URL}/collections", "rel": "data",
             "type": "application/json", "title": "Feature collections"},
        ],
    })


@app.route("/conformance")
def conformance():
    return jsonify({
        "conformsTo": [
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/cors",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
            "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
        ]
    })


@app.route("/api")
def api_definition():
    doc = {
        "openapi": "3.0.3",
        "info": {"title": "OGC API Features Server", "version": "1.0.0"},
        "servers": [{"url": BASE_URL}],
        "paths": {
            "/": {"get": {"summary": "Landing page", "operationId": "getLandingPage",
                          "responses": {"200": {"description": "OK"}}}},
            "/conformance": {"get": {"summary": "Conformance", "operationId": "getConformance",
                                     "responses": {"200": {"description": "OK"}}}},
            "/collections": {"get": {"summary": "Collections", "operationId": "getCollections",
                                     "responses": {"200": {"description": "OK"}}}},
            "/collections/{collectionId}": {
                "get": {"summary": "Collection", "operationId": "getCollection",
                        "parameters": [{"name": "collectionId", "in": "path",
                                        "required": True, "schema": {"type": "string"}}],
                        "responses": {"200": {"description": "OK"},
                                      "404": {"description": "Not found"}}}},
            "/collections/{collectionId}/items": {
                "get": {"summary": "Features", "operationId": "getFeatures",
                        "parameters": [
                            {"name": "collectionId", "in": "path", "required": True,
                             "schema": {"type": "string"}},
                            {"name": "limit", "in": "query",
                             "schema": {"type": "integer", "minimum": 1, "default": 10}},
                            {"name": "bbox", "in": "query",
                             "schema": {"type": "array", "items": {"type": "number"}}},
                            {"name": "datetime", "in": "query",
                             "schema": {"type": "string"}},
                        ],
                        "responses": {"200": {"description": "OK"},
                                      "400": {"description": "Bad request"}}}},
            "/collections/{collectionId}/items/{featureId}": {
                "get": {"summary": "Feature", "operationId": "getFeature",
                        "parameters": [
                            {"name": "collectionId", "in": "path", "required": True,
                             "schema": {"type": "string"}},
                            {"name": "featureId", "in": "path", "required": True,
                             "schema": {"type": "string"}},
                        ],
                        "responses": {"200": {"description": "OK"},
                                      "404": {"description": "Not found"}}}},
        },
    }
    return Response(json.dumps(doc, indent=2),
                    content_type="application/vnd.oai.openapi+json;version=3.0")


@app.route("/collections")
def get_collections():
    colls = []
    for cid, meta in collection_meta.items():
        c = dict(meta)
        c["links"] = [
            {"href": f"{BASE_URL}/collections/{cid}", "rel": "self",
             "type": "application/json"},
            {"href": f"{BASE_URL}/collections/{cid}/items", "rel": "items",
             "type": "application/geo+json"},
        ]
        colls.append(c)
    return jsonify({
        "collections": colls,
        "links": [{"href": f"{BASE_URL}/collections", "rel": "self",
                    "type": "application/json"}],
    })


@app.route("/collections/<cid>")
def get_collection(cid):
    if cid not in collection_meta:
        return jsonify({"code": "NotFound",
                        "description": f"Collection '{cid}' not found"}), 404
    c = dict(collection_meta[cid])
    c["links"] = [
        {"href": f"{BASE_URL}/collections/{cid}", "rel": "self",
         "type": "application/json"},
        {"href": f"{BASE_URL}/collections/{cid}/items", "rel": "items",
         "type": "application/geo+json"},
    ]
    return jsonify(c)


@app.route("/collections/<cid>/items")
def get_features(cid):
    if cid not in collections_data:
        return jsonify({"code": "NotFound",
                        "description": f"Collection '{cid}' not found"}), 404

    limit = 10
    if "limit" in request.args:
        try:
            limit = int(request.args["limit"])
        except ValueError:
            return jsonify({"code": "InvalidParameterValue",
                            "description": "limit must be an integer"}), 400
        if limit < 1:
            return jsonify({"code": "InvalidParameterValue",
                            "description": "limit must be >= 1"}), 400

    bbox = None
    if "bbox" in request.args:
        bbox = _parse_bbox(request.args["bbox"])
        if bbox is None:
            return jsonify({"code": "InvalidParameterValue",
                            "description": "Invalid bbox parameter"}), 400

    dt_range = None
    if "datetime" in request.args:
        try:
            dt_range = _parse_dt(request.args["datetime"])
        except Exception:
            return jsonify({"code": "InvalidParameterValue",
                            "description": "Invalid datetime parameter"}), 400

    offset = int(request.args.get("offset", 0))

    feats = collections_data[cid]
    if bbox:
        feats = [f for f in feats if _in_bbox(f.get("geometry"), bbox)]
    if dt_range:
        feats = [f for f in feats if _in_dt(f.get("properties"), dt_range)]

    matched = len(collections_data[cid])
    page = feats[offset:offset + limit]
    returned = len(page)

    links = [{"href": request.url, "rel": "self", "type": "application/geo+json"}]
    if offset + limit < len(feats):
        links.append({
            "href": f"{BASE_URL}/collections/{cid}/items?offset={offset + limit}&limit={limit}",
            "rel": "next",
            "type": "application/geo+json",
        })

    return _geojson({
        "type": "FeatureCollection",
        "features": page,
        "links": links,
        "numberMatched": matched,
        "numberReturned": returned,
    })


@app.route("/collections/<cid>/items/<fid>")
def get_feature(cid, fid):
    if cid not in collections_data:
        return jsonify({"code": "NotFound",
                        "description": f"Collection '{cid}' not found"}), 404
    for f in collections_data[cid]:
        if str(f.get("id")) == fid:
            result = dict(f)
            result["links"] = [
                {"href": f"{BASE_URL}/collections/{cid}/items/{fid}",
                 "rel": "self", "type": "application/geo+json"},
                {"href": f"{BASE_URL}/collections/{cid}",
                 "rel": "collection", "type": "application/json"},
            ]
            return _geojson(result)
    return jsonify({"code": "NotFound",
                    "description": f"Feature '{fid}' not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
