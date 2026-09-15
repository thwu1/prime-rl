#!/usr/bin/env python3
"""
Diagnose and fix all OGC API Features conformance violations.

Reads the stale TEAM Engine conformance report, cross-references it against
the current server code and data, identifies 9 violations spanning both the
server logic and source GeoJSON data, and applies targeted corrections.

Violations:
  Report-guided (3 real failures):
    - Conformance URI typo (cors -> core)
    - numberMatched uses total collection size, not filtered count
    - Open-ended datetime intervals (..) not supported
  Report red herring (1 false failure — already fixed):
    - Collection self links (present in current code, was missing in v0.7)
  Unreported code bugs (5):
    - CRS84 axis order in _in_bbox (lat/lon swapped)
    - service-desc link media type wrong
    - Extent bbox axis order wrong
    - Pagination next links drop filter params
    - Unknown query params not rejected
  Unreported data bug (1):
    - ws-003 GeoJSON coordinates in [lat,lon] instead of [lon,lat]
    (This bug masks the _in_bbox swap for ws-003 — two wrongs cancel.
     Must fix both for correct behavior.)
"""

import re
import xml.etree.ElementTree as ET
import json

# Step 1: Parse conformance report to understand reported failures
tree = ET.parse("/app/conformance-report.xml")
root = tree.getroot()
reported = []
for method in root.iter("test-method"):
    if method.get("status") == "FAIL":
        msg_el = method.find(".//message")
        reported.append((method.get("name"), (msg_el.text or "")[:80] if msg_el is not None else ""))

print(f"Conformance report: {len(reported)} reported failures")
for name, msg in reported:
    print(f"  FAIL: {name} — {msg}...")

# Identify the red herring: collection self links are already present in current code
print("\nAnalyzing report against current code...")
with open("/app/server.py") as f:
    code = f.read()

if '"rel": "self"' in code and "get_collections" in code:
    print("  NOTE: validateFeatureCollectionsMetaDataResponse_Links failure is stale")
    print("        — collection self links exist in current code (fixed after v0.7)")

# Step 2: Apply code fixes
fixes = 0

# Fix 1: CRS84 coordinate access order in _in_bbox
# GeoJSON uses [longitude, latitude] — code reads them backwards
old = 'lat, lon = geom["coordinates"][0], geom["coordinates"][1]'
new = 'lon, lat = geom["coordinates"][0], geom["coordinates"][1]'
if old in code:
    code = code.replace(old, new)
    fixes += 1
    print("\nFix 1: Corrected coordinate access in _in_bbox (CRS84: lon, lat)")

# Fix 2: numberMatched must use filtered count, not total collection size
old = "matched = len(collections_data[cid])"
new = "matched = len(feats)"
if old in code:
    code = code.replace(old, new)
    fixes += 1
    print("Fix 2: numberMatched now reflects filtered feature count")

# Fix 3: Conformance class URI typo (cors -> core)
old = '/conf/cors"'
new = '/conf/core"'
if old in code:
    code = code.replace(old, new)
    fixes += 1
    print("Fix 3: Corrected Core conformance class URI (cors -> core)")

# Fix 4: service-desc link media type must reference OpenAPI
old = '"type": "application/json", "title": "API definition"'
new = '"type": "application/vnd.oai.openapi+json;version=3.0", "title": "API definition"'
if old in code:
    code = code.replace(old, new)
    fixes += 1
    print("Fix 4: Corrected service-desc link media type to OpenAPI")

# Fix 5: Open-ended datetime interval support (..)
# Use regex for more robust matching across whitespace variations
dt_pattern = re.compile(
    r'(\s+)start = dt_cls\.fromisoformat\(a\.replace\("Z", "\+00:00"\)\)\n'
    r'\s+end = dt_cls\.fromisoformat\(b\.replace\("Z", "\+00:00"\)\)'
)
dt_match = dt_pattern.search(code)
if dt_match:
    indent = dt_match.group(1)
    old_dt = dt_match.group(0)
    new_dt = (
        f'{indent}start = None if a == ".." else dt_cls.fromisoformat(a.replace("Z", "+00:00"))\n'
        f'{indent}end = None if b == ".." else dt_cls.fromisoformat(b.replace("Z", "+00:00"))'
    )
    code = code.replace(old_dt, new_dt)
    fixes += 1
    print("Fix 5: Added open-ended interval (..) support in _parse_dt")

# Fix 6: Pagination next link must preserve filter query params
# Use regex for robustness
next_pattern = re.compile(
    r'(\s+)links\.append\(\{\n'
    r'\s+"href": f"\{BASE_URL\}/collections/\{cid\}/items\?offset=\{offset \+ limit\}&limit=\{limit\}",\n'
    r'\s+"rel": "next",\n'
    r'\s+"type": "application/geo\+json",\n'
    r'\s+\}\)'
)
next_match = next_pattern.search(code)
if next_match:
    indent = next_match.group(1)
    old_next = next_match.group(0)
    new_next = (
        f'{indent}parts = [f"offset={{offset + limit}}", f"limit={{limit}}"]\n'
        f'{indent}if "bbox" in request.args:\n'
        f'{indent}    parts.append(f"bbox={{request.args[\'bbox\']}}")\n'
        f'{indent}if "datetime" in request.args:\n'
        f'{indent}    parts.append(f"datetime={{request.args[\'datetime\']}}")\n'
        f'{indent}links.append({{\n'
        f'{indent}    "href": f"{{BASE_URL}}/collections/{{cid}}/items?{{\'&\'.join(parts)}}",\n'
        f'{indent}    "rel": "next",\n'
        f'{indent}    "type": "application/geo+json",\n'
        f'{indent}}})'
    )
    code = code.replace(old_next, new_next)
    fixes += 1
    print("Fix 6: Pagination next link now preserves bbox/datetime params")

# Fix 7: Extent bbox axis order must be CRS84 [lon, lat, lon, lat]
old_extent = '"bbox": [[min(_lats), min(_lons), max(_lats), max(_lons)]]'
new_extent = '"bbox": [[min(_lons), min(_lats), max(_lons), max(_lats)]]'
if old_extent in code:
    code = code.replace(old_extent, new_extent)
    fixes += 1
    print("Fix 7: Corrected extent bbox axis order to CRS84 (lon, lat)")

# Fix 8: Add unknown query parameter validation (HTTP 400)
old_limit = "    limit = 10\n    if \"limit\" in request.args:"
new_limit = (
    '    known_params = {"limit", "bbox", "datetime", "offset"}\n'
    "    for p in request.args:\n"
    "        if p not in known_params:\n"
    '            return jsonify({"code": "InvalidParameterValue",\n'
    '                            "description": f"Unknown query parameter: {p}"}), 400\n'
    "\n"
    "    limit = 10\n"
    '    if "limit" in request.args:'
)
if old_limit in code:
    code = code.replace(old_limit, new_limit, 1)
    fixes += 1
    print("Fix 8: Added unknown query parameter validation (HTTP 400)")

# Write fixed server code
with open("/app/server.py", "w") as f:
    f.write(code)

print(f"\nApplied {fixes}/8 code fixes to /app/server.py")

# Verify critical fixes were applied
with open("/app/server.py") as f:
    fixed_code = f.read()

checks = [
    ("lon, lat = geom" in fixed_code, "Fix 1: coordinate order"),
    ("matched = len(feats)" in fixed_code, "Fix 2: numberMatched"),
    ("/conf/core" in fixed_code, "Fix 3: conformance URI"),
    ("openapi" in fixed_code.lower(), "Fix 4: service-desc type"),
    ('if a == ".."' in fixed_code or "None if a" in fixed_code, "Fix 5: open interval"),
    ("bbox={request.args" in fixed_code or "bbox=" in fixed_code.split("parts")[1] if "parts" in fixed_code else False, "Fix 6: pagination filter"),
    ("min(_lons), min(_lats)" in fixed_code, "Fix 7: extent order"),
    ("known_params" in fixed_code, "Fix 8: param validation"),
]

all_ok = True
for ok, name in checks:
    if not ok:
        print(f"  WARNING: {name} may not have been applied!")
        all_ok = False

if all_ok:
    print("All 8 code fixes verified successfully")

# Step 3: Fix data-layer bug
# ws-003 (Tokyo Haneda) has coordinates in [lat, lon] order instead of
# GeoJSON-mandated [lon, lat]. This bug masked the _in_bbox coordinate swap
# for this specific feature (two wrongs cancelled out).
with open("/app/data/weather_stations.geojson") as f:
    ws_data = json.load(f)

data_fixes = 0
for feat in ws_data["features"]:
    if feat["id"] == "ws-003":
        coords = feat["geometry"]["coordinates"]
        # Tokyo: lon ~139.7, lat ~35.7
        # If coords[0] < 90 and coords[1] > 90, they're swapped
        if abs(coords[0]) < 90 and abs(coords[1]) > 90:
            feat["geometry"]["coordinates"] = [coords[1], coords[0]]
            data_fixes += 1
            print(f"\nFix 9: Corrected ws-003 GeoJSON coordinate order")
            print(f"  Was: [{coords[0]}, {coords[1]}] (lat, lon)")
            print(f"  Now: [{coords[1]}, {coords[0]}] (lon, lat)")
        break

with open("/app/data/weather_stations.geojson", "w") as f:
    json.dump(ws_data, f)

print(f"\nApplied {data_fixes}/1 data fixes to weather_stations.geojson")
print(f"\nTotal: {fixes + data_fixes}/9 conformance fixes applied")
