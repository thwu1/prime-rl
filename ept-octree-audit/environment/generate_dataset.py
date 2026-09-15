#!/usr/bin/env python3
"""Generate EPT dataset with LAS 1.4 PDRF 6 data tiles and intentional errors.

Errors introduced:
  EPT metadata:
    1. Non-cubic bounds (Z range shrunk)
    2. boundsConforming x_max exceeds outer bounds
    3. Hierarchy counts inflated for 3 nodes
    4. Spatial misassignment (points moved between sibling nodes)
    5. Schema phantom NIR dimension
    6. Total point count wrong (+42)
  LAS / USGS LBS:
    7. Classification 0 (Never Classified) — USGS prohibited
    8. Classification 12 (overlap by class) — USGS: must use overlap bit flag
    9. ReturnNumber > NumberOfReturns for ~3% of points — LAS 1.4 violation
   10. FileSourceID non-zero in tiled data — USGS LBS violation
"""
import json
import os
import random
import shutil

import numpy as np
import laspy

random.seed(42)
np.random.seed(42)

BASE = "/app/dataset"
SPAN = 64
N = 5000

if os.path.exists(BASE):
    shutil.rmtree(BASE)
os.makedirs(f"{BASE}/ept-data", exist_ok=True)
os.makedirs(f"{BASE}/ept-hierarchy", exist_ok=True)

# --------------- generate point attributes ---------------
x = np.round(np.random.uniform(500000.0, 500480.0, N), 3)
y = np.round(np.random.uniform(4500000.0, 4500480.0, N), 3)
z = np.round(np.random.uniform(100.0, 340.0, N), 3)
intensity = np.random.randint(100, 60000, N).astype(np.uint16)
gps_time = 1000000.0 + np.random.uniform(0, 86400.0, N)
point_ids = np.arange(N, dtype=np.uint32)

# classifications (errors 7 & 8)
cls = np.ones(N, dtype=np.uint8)
r = np.random.random(N)
cls[r < 0.35] = 1
cls[(r >= 0.35) & (r < 0.70)] = 2
cls[(r >= 0.70) & (r < 0.74)] = 7
cls[(r >= 0.74) & (r < 0.82)] = 9
cls[(r >= 0.82) & (r < 0.85)] = 17
cls[(r >= 0.85) & (r < 0.88)] = 18
cls[(r >= 0.88) & (r < 0.91)] = 0   # ERROR 7
cls[(r >= 0.91) & (r < 0.93)] = 12  # ERROR 8
cls[(r >= 0.93) & (r < 0.96)] = 3
cls[(r >= 0.96)] = 6

# return numbers (error 9)
ret_num = np.random.randint(1, 4, N).astype(np.uint8)
num_ret = np.random.randint(1, 4, N).astype(np.uint8)
num_ret = np.maximum(num_ret, ret_num)
violation_mask = np.random.random(N) < 0.03
ret_num[violation_mask] = (num_ret[violation_mask] + 1).astype(np.uint8)

# --------------- build octree ---------------
points = []
for i in range(N):
    points.append({
        "PointId": int(point_ids[i]),
        "X": float(x[i]),
        "Y": float(y[i]),
        "Z": float(z[i]),
        "Intensity": int(intensity[i]),
        "Classification": int(cls[i]),
        "ReturnNumber": int(ret_num[i]),
        "NumberOfReturns": int(num_ret[i]),
        "GPSTime": float(gps_time[i]),
    })

xs = [p["X"] for p in points]
ys = [p["Y"] for p in points]
zs = [p["Z"] for p in points]
conf = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
ranges_d = [conf[3] - conf[0], conf[4] - conf[1], conf[5] - conf[2]]
max_range = max(ranges_d)
center = [(conf[i] + conf[i + 3]) / 2 for i in range(3)]
cube = [
    round(center[0] - max_range / 2, 3),
    round(center[1] - max_range / 2, 3),
    round(center[2] - max_range / 2, 3),
    round(center[0] + max_range / 2, 3),
    round(center[1] + max_range / 2, 3),
    round(center[2] + max_range / 2, 3),
]


def get_octant(pt, bounds):
    mid = [(bounds[i] + bounds[i + 3]) / 2 for i in range(3)]
    return (
        0 if pt["X"] < mid[0] else 1,
        0 if pt["Y"] < mid[1] else 1,
        0 if pt["Z"] < mid[2] else 1,
    )


def child_bounds(bounds, dx, dy, dz):
    mid = [(bounds[i] + bounds[i + 3]) / 2 for i in range(3)]
    return [
        bounds[0] if dx == 0 else mid[0],
        bounds[1] if dy == 0 else mid[1],
        bounds[2] if dz == 0 else mid[2],
        mid[0] if dx == 0 else bounds[3],
        mid[1] if dy == 0 else bounds[4],
        mid[2] if dz == 0 else bounds[5],
    ]


def build_tree(pts, bounds, d, xi, yi, zi):
    key = f"{d}-{xi}-{yi}-{zi}"
    if len(pts) <= SPAN or d >= 8:
        return {key: list(pts)}
    buckets = {}
    for p in pts:
        o = get_octant(p, bounds)
        buckets.setdefault(o, []).append(p)
    result = {}
    for (dx, dy, dz), bpts in buckets.items():
        cb = child_bounds(bounds, dx, dy, dz)
        result.update(
            build_tree(bpts, cb, d + 1, 2 * xi + dx, 2 * yi + dy, 2 * zi + dz)
        )
    return result


nodes = build_tree(points, cube, 0, 0, 0, 0)

# correct hierarchy (before swap)
hierarchy = {k: len(v) for k, v in nodes.items()}
total_pts = sum(hierarchy.values())

# --------------- error 4: spatial misassignment ---------------
node_keys = sorted(nodes.keys())
swap_src = swap_dst = None
for k in node_keys:
    parts = k.split("-")
    d, nx, ny, nz = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    sib = f"{d}-{nx ^ 1}-{ny}-{nz}"
    if sib in nodes and len(nodes[k]) >= 15:
        swap_src, swap_dst = k, sib
        break
assert swap_src is not None
MOVE_COUNT = min(10, len(nodes[swap_src]) - 5)
moved = nodes[swap_src][:MOVE_COUNT]
nodes[swap_src] = nodes[swap_src][MOVE_COUNT:]
nodes[swap_dst] = nodes[swap_dst] + moved

# --------------- write LAS data tiles ---------------


def write_las_node(filepath, pts, fsi=0):
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([500000.0, 4500000.0, 0.0])
    header.file_source_id = fsi
    header.add_extra_dim(
        laspy.ExtraBytesParams(name="PointId", type=np.uint32)
    )
    las = laspy.LasData(header)
    las.x = np.array([p["X"] for p in pts])
    las.y = np.array([p["Y"] for p in pts])
    las.z = np.array([p["Z"] for p in pts])
    las.intensity = np.array([p["Intensity"] for p in pts], dtype=np.uint16)
    las.classification = np.array(
        [p["Classification"] for p in pts], dtype=np.uint8
    )
    las.return_number = np.array(
        [p["ReturnNumber"] for p in pts], dtype=np.uint8
    )
    las.number_of_returns = np.array(
        [p["NumberOfReturns"] for p in pts], dtype=np.uint8
    )
    las.gps_time = np.array([p["GPSTime"] for p in pts])
    las.PointId = np.array([p["PointId"] for p in pts], dtype=np.uint32)
    las.write(filepath)


for key, pts in nodes.items():
    fsi = random.randint(100, 999)  # ERROR 10: non-zero for tiled data
    write_las_node(f"{BASE}/ept-data/{key}.las", pts, fsi=fsi)

# --------------- EPT metadata errors ---------------
inflate_keys = [k for k in node_keys if k not in (swap_src, swap_dst)][:3]
bad_hierarchy = dict(hierarchy)
for nk in inflate_keys:
    bad_hierarchy[nk] += random.randint(2, 5)

# error 1: non-cubic bounds
bad_bounds = list(cube)
bad_bounds[2] = round(center[2] - max_range * 0.25, 3)
bad_bounds[5] = round(center[2] + max_range * 0.25, 3)

# error 2: boundsConforming exceeds bounds
bad_conf = list(conf)
bad_conf[3] = round(bad_bounds[3] + 10.0, 3)

# error 5: phantom NIR dimension
schema = [
    {"name": "X", "type": "float", "size": 8, "scale": 0.001, "offset": 500000},
    {"name": "Y", "type": "float", "size": 8, "scale": 0.001, "offset": 4500000},
    {"name": "Z", "type": "float", "size": 8, "scale": 0.001, "offset": 0},
    {"name": "Intensity", "type": "unsigned", "size": 2},
    {"name": "Classification", "type": "unsigned", "size": 1},
    {"name": "ReturnNumber", "type": "unsigned", "size": 1},
    {"name": "NumberOfReturns", "type": "unsigned", "size": 1},
    {"name": "GPSTime", "type": "float", "size": 8},
    {"name": "PointId", "type": "unsigned", "size": 4},
    {"name": "NIR", "type": "unsigned", "size": 2},
]

# error 6: total point count wrong
bad_total = total_pts + 42

ept_json = {
    "bounds": bad_bounds,
    "boundsConforming": bad_conf,
    "dataType": "las",
    "hierarchyType": "json",
    "points": bad_total,
    "schema": schema,
    "span": SPAN,
    "srs": {
        "authority": "EPSG",
        "horizontal": "6344",
        "vertical": "5703",
        "wkt": (
            'COMPD_CS["NAD83(2011) / UTM zone 15N + NAVD88 height",'
            'PROJCS["NAD83(2011) / UTM zone 15N",'
            'GEOGCS["NAD83(2011)",'
            'DATUM["NAD83_National_Spatial_Reference_Frame_2011",'
            'SPHEROID["GRS 1980",6378137,298.257222101]],'
            'PRIMEM["Greenwich",0],'
            'UNIT["degree",0.0174532925199433]],'
            'PROJECTION["Transverse_Mercator"],'
            'PARAMETER["latitude_of_origin",0],'
            'PARAMETER["central_meridian",-93],'
            'PARAMETER["scale_factor",0.9996],'
            'PARAMETER["false_easting",500000],'
            'PARAMETER["false_northing",0],'
            'UNIT["metre",1]],'
            'VERT_CS["NAVD88 height (geoid18)",'
            'VERT_DATUM["North American Vertical Datum 1988",2005],'
            'UNIT["metre",1]]]'
        ),
    },
    "version": "1.0.0",
}

with open(f"{BASE}/ept.json", "w") as f:
    json.dump(ept_json, f, indent=2)

with open(f"{BASE}/ept-hierarchy/0-0-0-0.json", "w") as f:
    json.dump(bad_hierarchy, f, indent=2)

print(f"Generated {len(nodes)} nodes, {total_pts} points")
print(f"Swap: {swap_src} -> {swap_dst} ({MOVE_COUNT} pts)")
print(f"Inflated: {inflate_keys}")
