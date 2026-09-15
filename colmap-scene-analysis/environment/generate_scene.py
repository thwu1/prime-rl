#!/usr/bin/env python3
"""Generate corrupted COLMAP sparse reconstruction with ground truth database."""
import struct
import os
import math
import random
import sqlite3


def wb(fid, data, fmt, e="<"):
    fid.write(struct.pack(
        e + fmt, *(data if isinstance(data, (list, tuple)) else [data])))


def qvec2rotmat(q):
    w, x, y, z = q
    return [[1-2*y*y-2*z*z, 2*x*y-2*w*z, 2*z*x+2*w*y],
            [2*x*y+2*w*z, 1-2*x*x-2*z*z, 2*y*z-2*w*x],
            [2*z*x-2*w*y, 2*y*z+2*w*x, 1-2*x*x-2*y*y]]


def rotmat2qvec(R):
    tr = R[0][0] + R[1][1] + R[2][2]
    if tr > 0:
        s = 0.5 / math.sqrt(tr + 1.0)
        w = 0.25 / s
        x = (R[2][1] - R[1][2]) * s
        y = (R[0][2] - R[2][0]) * s
        z = (R[1][0] - R[0][1]) * s
    elif R[0][0] > R[1][1] and R[0][0] > R[2][2]:
        s = 2.0 * math.sqrt(1.0 + R[0][0] - R[1][1] - R[2][2])
        w = (R[2][1] - R[1][2]) / s
        x = 0.25 * s
        y = (R[0][1] + R[1][0]) / s
        z = (R[0][2] + R[2][0]) / s
    elif R[1][1] > R[2][2]:
        s = 2.0 * math.sqrt(1.0 + R[1][1] - R[0][0] - R[2][2])
        w = (R[0][2] - R[2][0]) / s
        x = (R[0][1] + R[1][0]) / s
        y = 0.25 * s
        z = (R[1][2] + R[2][1]) / s
    else:
        s = 2.0 * math.sqrt(1.0 + R[2][2] - R[0][0] - R[1][1])
        w = (R[1][0] - R[0][1]) / s
        x = (R[0][2] + R[2][0]) / s
        y = (R[1][2] + R[2][1]) / s
        z = 0.25 * s
    q = [w, x, y, z]
    if w < 0:
        q = [-v for v in q]
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q]


def look_at(pos, tgt=None):
    if tgt is None:
        tgt = [0., 0., 0.]

    def vn(v):
        n = math.sqrt(sum(a * a for a in v))
        return [a / n for a in v]

    def cr(a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    up = [0., 0., 1.]
    fwd = vn([tgt[i] - pos[i] for i in range(3)])
    rt = cr(fwd, up)
    if math.sqrt(sum(a * a for a in rt)) < 1e-6:
        up = [0., 1., 0.]
        rt = cr(fwd, up)
    rt = vn(rt)
    nu = vn(cr(rt, fwd))
    R = [rt, [-a for a in nu], fwd]
    t = [-sum(R[i][j] * pos[j] for j in range(3)) for i in range(3)]
    return R, t


def randn(rng):
    u1, u2 = rng.random(), rng.random()
    while u1 == 0:
        u1 = rng.random()
    return math.sqrt(-2 * math.log(u1)) * math.cos(2 * math.pi * u2)


# ============================================================
# Scene definition (ground truth)
# ============================================================
cams = {
    1: {"mid": 1, "w": 1920, "h": 1080,
        "p": [1000.0, 1000.0, 960.0, 540.0]},       # PINHOLE
    2: {"mid": 0, "w": 1280, "h": 720,
        "p": [800.0, 640.0, 360.0]},                  # SIMPLE_PINHOLE
}

cpos = [
    [5., 0., 0.], [0., 5., 0.], [-5., 0., 0.], [0., -5., 0.],
    [3.5, 3.5, 2.], [-3.5, -3.5, -1.], [4., 0., 3.], [0., 4., -2.],
]
cassign = [1, 1, 1, 1, 2, 2, 2, 2]

imgs = {}
for i, (pos, cid) in enumerate(zip(cpos, cassign)):
    iid = i + 1
    R, t = look_at(pos)
    q = rotmat2qvec(R)
    imgs[iid] = {"q": q, "t": t, "cid": cid,
                 "name": "img_{:04d}.jpg".format(iid), "wp": pos[:]}

rng_p = random.Random(42)
pts = [[randn(rng_p) * 1.5, randn(rng_p) * 1.5, randn(rng_p) * 1.5]
       for _ in range(80)]

# Override specific points for behind-camera and triangulation testing
pts[0] = [8.0, 0.5, 0.0]      # behind camera at image 1 position
pts[1] = [0.5, 8.0, 0.0]      # behind camera at image 2 position
pts[73] = [7.0, -1.0, 0.0]    # behind camera at image 1 position
pts[74] = [-1.0, 7.0, 0.0]    # behind camera at image 2 position
pts[75] = [0.0, 0.0, 300.0]   # distant point — low max triangulation angle
pts[76] = [300.0, 0.0, 0.0]   # distant point — low max triangulation angle
pts[77] = [0.0, 300.0, 0.0]   # distant point — low max triangulation angle

pvis = {}
for pi in range(80):
    xyz = pts[pi]
    vis = []
    for iid, im in imgs.items():
        R = qvec2rotmat(im["q"])
        zc = sum(R[2][c] * xyz[c] for c in range(3)) + im["t"][2]
        if zc > 0.1:
            vis.append(iid)
    if len(vis) >= 2:
        rv = random.Random(42 + pi)
        nv = min(len(vis), max(2, rv.randint(2, min(5, len(vis)))))
        pvis[pi] = sorted(rv.sample(vis, nv))

iobs = {iid: [] for iid in imgs}
p3d = {}
ro = random.Random(123)
for pi in sorted(pvis.keys()):
    pid = pi + 1
    ti, tp = [], []
    for iid in pvis[pi]:
        tp.append(len(iobs[iid]))
        iobs[iid].append(((ro.uniform(10, 1900), ro.uniform(10, 1060)), pid))
        ti.append(iid)
    p3d[pid] = {
        "xyz": pts[pi][:],
        "rgb": [ro.randint(0, 255) for _ in range(3)],
        "err": ro.uniform(0.1, 2.0),
        "ti": ti,
        "tp": tp,
    }

for iid in imgs:
    for _ in range(ro.randint(5, 14)):
        iobs[iid].append(
            ((ro.uniform(10, 1900), ro.uniform(10, 1060)), -1))

# ============================================================
# Ground truth SQLite database
# ============================================================
os.makedirs("/app/scene", exist_ok=True)
db_path = "/app/scene/database.db"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

cur.execute("""CREATE TABLE cameras (
    camera_id INTEGER PRIMARY KEY NOT NULL,
    model INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    params BLOB,
    prior_focal_length INTEGER NOT NULL DEFAULT 0
)""")

cur.execute("""CREATE TABLE images (
    image_id INTEGER PRIMARY KEY NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    camera_id INTEGER NOT NULL
)""")

for cid in sorted(cams):
    cam = cams[cid]
    params_blob = struct.pack("<" + "d" * len(cam["p"]), *cam["p"])
    cur.execute("INSERT INTO cameras VALUES (?, ?, ?, ?, ?, ?)",
                (cid, cam["mid"], cam["w"], cam["h"], params_blob, 1))

for iid in sorted(imgs):
    im = imgs[iid]
    cur.execute("INSERT INTO images VALUES (?, ?, ?)",
                (iid, im["name"], im["cid"]))

conn.commit()
conn.close()

# ============================================================
# Inject corruptions
# ============================================================

# 1. Camera 1 focal lengths scaled 100x
corrupted_cam_params = {}
for cid in cams:
    corrupted_cam_params[cid] = cams[cid]["p"][:]
corrupted_cam_params[1][0] = 100000.0   # fx
corrupted_cam_params[1][1] = 100000.0   # fy

# 2. Denormalize quaternions for images 3 and 6
corrupted_qvecs = {}
for iid in imgs:
    corrupted_qvecs[iid] = imgs[iid]["q"][:]
for iid in [3, 6]:
    corrupted_qvecs[iid] = [v * 1.3 for v in imgs[iid]["q"]]

# 3. Swap camera assignments for images 2 and 5
corrupted_camids = {}
for iid in imgs:
    corrupted_camids[iid] = imgs[iid]["cid"]
corrupted_camids[2] = 2   # should be 1
corrupted_camids[5] = 1   # should be 2

# 4. Orphan track references (image_id 99 does not exist)
sorted_pids = sorted(p3d.keys())
assert len(sorted_pids) >= 5
orphan_pids = sorted_pids[:5]

corrupted_tracks = {}
for pid in p3d:
    corrupted_tracks[pid] = {
        "ti": p3d[pid]["ti"][:],
        "tp": p3d[pid]["tp"][:],
    }
for pid in orphan_pids:
    corrupted_tracks[pid]["ti"].append(99)
    corrupted_tracks[pid]["tp"].append(0)

# 5. Behind-camera track entries (valid image IDs but point projects behind camera)
behind_camera_injections = {
    1: 1,    # PID 1 (pts[0]=[8,0.5,0]) — behind image 1's camera at [5,0,0]
    2: 2,    # PID 2 (pts[1]=[0.5,8,0]) — behind image 2's camera at [0,5,0]
    74: 1,   # PID 74 (pts[73]=[7,-1,0]) — behind image 1's camera
    75: 2,   # PID 75 (pts[74]=[-1,7,0]) — behind image 2's camera
}
for pid, img_id in behind_camera_injections.items():
    assert pid in corrupted_tracks, \
        "PID {} not in corrupted_tracks (available: {})".format(
            pid, sorted(corrupted_tracks.keys())[:10])
    corrupted_tracks[pid]["ti"].append(img_id)
    corrupted_tracks[pid]["tp"].append(0)

# ============================================================
# Write corrupted binary files
# ============================================================
out = "/app/scene/sparse/0"
os.makedirs(out, exist_ok=True)

with open(os.path.join(out, "cameras.bin"), "wb") as f:
    wb(f, len(cams), "Q")
    for cid in sorted(cams):
        c = cams[cid]
        wb(f, [cid, c["mid"], c["w"], c["h"]], "iiQQ")
        for p in corrupted_cam_params[cid]:
            wb(f, p, "d")

with open(os.path.join(out, "images.bin"), "wb") as f:
    wb(f, len(imgs), "Q")
    for iid in sorted(imgs):
        im = imgs[iid]
        wb(f, iid, "i")
        wb(f, corrupted_qvecs[iid], "dddd")
        wb(f, im["t"], "ddd")
        wb(f, corrupted_camids[iid], "i")
        for ch in im["name"]:
            wb(f, ch.encode("utf-8"), "c")
        wb(f, b"\x00", "c")
        obs = iobs[iid]
        wb(f, len(obs), "Q")
        for (xy, pid) in obs:
            wb(f, [xy[0], xy[1], pid], "ddq")

with open(os.path.join(out, "points3D.bin"), "wb") as f:
    wb(f, len(p3d), "Q")
    for pid in sorted(p3d):
        pt = p3d[pid]
        wb(f, pid, "Q")
        wb(f, pt["xyz"], "ddd")
        wb(f, pt["rgb"], "BBB")
        wb(f, pt["err"], "d")
        ti = corrupted_tracks[pid]["ti"]
        tp = corrupted_tracks[pid]["tp"]
        wb(f, len(ti), "Q")
        for a, b in zip(ti, tp):
            wb(f, [a, b], "ii")

# ============================================================
# Readback verification — confirm all injections survived binary I/O
# ============================================================
print("Scene generation complete")
print("Points in scene: {}".format(len(p3d)))
print("Orphan injections: PIDs {}".format(orphan_pids))
print("Behind-camera injections: {}".format(behind_camera_injections))

# Read back points3D.bin and verify behind-camera entries
verify_pts = {}
with open(os.path.join(out, "points3D.bin"), "rb") as f:
    num = struct.unpack("<Q", f.read(8))[0]
    for _ in range(num):
        props = struct.unpack("<QdddBBBd", f.read(43))
        pt_id = props[0]
        xyz = list(props[1:4])
        track_len = struct.unpack("<Q", f.read(8))[0]
        track = []
        for _ in range(track_len):
            iid, pidx = struct.unpack("<ii", f.read(8))
            track.append(iid)
        verify_pts[pt_id] = {"xyz": xyz, "track": track}

# Read back images.bin for z_cam verification
verify_imgs = {}
with open(os.path.join(out, "images.bin"), "rb") as f:
    num = struct.unpack("<Q", f.read(8))[0]
    for _ in range(num):
        props = struct.unpack("<idddddddi", f.read(64))
        img_id = props[0]
        qvec = list(props[1:5])
        tvec = list(props[5:8])
        name = b""
        ch = f.read(1)
        while ch != b"\x00":
            name += ch
            ch = f.read(1)
        num_obs = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num_obs):
            f.read(24)
        verify_imgs[img_id] = {"qvec": qvec, "tvec": tvec}

verified_count = 0
for pid, img_id in behind_camera_injections.items():
    assert pid in verify_pts, \
        "VERIFY FAIL: PID {} missing from binary".format(pid)
    assert img_id in verify_pts[pid]["track"], \
        "VERIFY FAIL: PID {} missing behind-camera img {}; track={}".format(
            pid, img_id, verify_pts[pid]["track"])
    xyz = verify_pts[pid]["xyz"]
    im = verify_imgs[img_id]
    qn = math.sqrt(sum(v * v for v in im["qvec"]))
    R = qvec2rotmat([v / qn for v in im["qvec"]])
    z_cam = sum(R[2][c] * xyz[c] for c in range(3)) + im["tvec"][2]
    assert z_cam < 0, \
        "VERIFY FAIL: PID {} img {} z_cam={:.4f} (expected negative)".format(
            pid, img_id, z_cam)
    verified_count += 1
    print("  Verified: PID {} img {} z_cam={:.4f}".format(pid, img_id, z_cam))

print("Readback verification passed: {}/{} behind-camera entries confirmed".format(
    verified_count, len(behind_camera_injections)))
