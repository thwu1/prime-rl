
import json
import os
import math
import struct
import sqlite3
import pytest


CAMERA_MODEL_NUM_PARAMS = {
    0: 3, 1: 4, 2: 4, 3: 5, 4: 8, 5: 8,
    6: 12, 7: 5, 8: 4, 9: 5, 10: 12,
}

DB_PATH = "/app/scene/database.db"
ORIG_DIR = "/app/scene/sparse/0"
REPAIR_DIR = "/app/repaired"
REPORT_PATH = "/app/diagnostic_report.json"
CONFIG_PATH = "/app/scene_config.json"
RTOL = 1e-4


# ---- Binary parsers ----

def read_cameras_bin(path):
    cameras = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            cam_id, model_id = struct.unpack("<ii", f.read(8))
            width, height = struct.unpack("<QQ", f.read(16))
            nparams = CAMERA_MODEL_NUM_PARAMS[model_id]
            params = list(struct.unpack(
                "<" + "d" * nparams, f.read(8 * nparams)))
            cameras[cam_id] = {
                "model_id": model_id, "width": width,
                "height": height, "params": params,
            }
    return cameras


def read_images_bin(path):
    images = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            props = struct.unpack("<idddddddi", f.read(64))
            img_id = props[0]
            qvec = list(props[1:5])
            tvec = list(props[5:8])
            camera_id = props[8]
            name = b""
            ch = f.read(1)
            while ch != b"\x00":
                name += ch
                ch = f.read(1)
            name = name.decode("utf-8")
            num_obs = struct.unpack("<Q", f.read(8))[0]
            observations = []
            for _ in range(num_obs):
                x, y, p3d_id = struct.unpack("<ddq", f.read(24))
                observations.append((x, y, p3d_id))
            images[img_id] = {
                "qvec": qvec, "tvec": tvec,
                "camera_id": camera_id, "name": name,
                "observations": observations,
            }
    return images


def read_points3d_bin(path):
    points = {}
    with open(path, "rb") as f:
        num = struct.unpack("<Q", f.read(8))[0]
        for _ in range(num):
            props = struct.unpack("<QdddBBBd", f.read(43))
            pt_id = props[0]
            xyz = list(props[1:4])
            rgb = list(props[4:7])
            error = props[7]
            track_len = struct.unpack("<Q", f.read(8))[0]
            track = []
            for _ in range(track_len):
                iid, pidx = struct.unpack("<ii", f.read(8))
                track.append((iid, pidx))
            points[pt_id] = {
                "xyz": xyz, "rgb": rgb,
                "error": error, "track": track,
            }
    return points


# ---- Geometric helpers ----

def qvec2rotmat(q):
    w, x, y, z = q
    return [[1-2*y*y-2*z*z, 2*x*y-2*w*z, 2*z*x+2*w*y],
            [2*x*y+2*w*z, 1-2*x*x-2*z*z, 2*y*z-2*w*x],
            [2*z*x-2*w*y, 2*y*z+2*w*x, 1-2*x*x-2*y*y]]


def camera_world_pos(qvec, tvec):
    R = qvec2rotmat(qvec)
    Rt = [[R[j][i] for j in range(3)] for i in range(3)]
    return [-sum(Rt[i][j] * tvec[j] for j in range(3)) for i in range(3)]


# ---- Database helpers ----

def get_db_cameras():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cameras = {}
    for row in cur.execute(
            "SELECT camera_id, model, width, height, params FROM cameras"):
        cam_id, model, width, height, params_blob = row
        nparams = CAMERA_MODEL_NUM_PARAMS[model]
        params = list(struct.unpack(
            "<" + "d" * nparams, params_blob))
        cameras[cam_id] = {
            "model_id": model, "width": width,
            "height": height, "params": params,
        }
    conn.close()
    return cameras


def get_db_image_assignments():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    assignments = {}
    for row in cur.execute("SELECT image_id, camera_id FROM images"):
        assignments[row[0]] = row[1]
    conn.close()
    return assignments


# ============================================================
# Tests
# ============================================================

class TestRepairedFilesExist:
    def test_cameras_bin_exists(self):
        assert os.path.isfile(os.path.join(REPAIR_DIR, "cameras.bin")), \
            "Repaired cameras.bin not found"

    def test_images_bin_exists(self):
        assert os.path.isfile(os.path.join(REPAIR_DIR, "images.bin")), \
            "Repaired images.bin not found"

    def test_points3d_bin_exists(self):
        assert os.path.isfile(os.path.join(REPAIR_DIR, "points3D.bin")), \
            "Repaired points3D.bin not found"


class TestCameraIntrinsics:
    def test_camera_count(self):
        cameras = read_cameras_bin(
            os.path.join(REPAIR_DIR, "cameras.bin"))
        assert len(cameras) == 2, \
            "Expected 2 cameras, got {}".format(len(cameras))

    def test_camera_params_match_database(self):
        repaired = read_cameras_bin(
            os.path.join(REPAIR_DIR, "cameras.bin"))
        expected = get_db_cameras()
        for cam_id in expected:
            assert cam_id in repaired, \
                "Camera {} missing from repaired file".format(cam_id)
            for i, (a, b) in enumerate(zip(
                    repaired[cam_id]["params"],
                    expected[cam_id]["params"])):
                denom = max(abs(b), 1e-10)
                rel_err = abs(a - b) / denom
                assert rel_err < RTOL, \
                    "Camera {} param[{}]: repaired={}, expected={}".format(
                        cam_id, i, a, b)

    def test_camera_dimensions_preserved(self):
        repaired = read_cameras_bin(
            os.path.join(REPAIR_DIR, "cameras.bin"))
        expected = get_db_cameras()
        for cam_id in expected:
            assert repaired[cam_id]["width"] == expected[cam_id]["width"]
            assert repaired[cam_id]["height"] == expected[cam_id]["height"]

    def test_camera_model_ids_preserved(self):
        repaired = read_cameras_bin(
            os.path.join(REPAIR_DIR, "cameras.bin"))
        expected = get_db_cameras()
        for cam_id in expected:
            assert repaired[cam_id]["model_id"] == expected[cam_id]["model_id"]


class TestImagePoses:
    def test_image_count(self):
        images = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        assert len(images) == 8, \
            "Expected 8 images, got {}".format(len(images))

    def test_all_quaternions_normalized(self):
        images = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        for iid, img in images.items():
            q = img["qvec"]
            norm = math.sqrt(sum(x * x for x in q))
            assert abs(norm - 1.0) < RTOL, \
                "Image {}: quaternion norm = {}, expected 1.0".format(
                    iid, norm)

    def test_camera_assignments_match_database(self):
        images = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        expected = get_db_image_assignments()
        for iid, img in images.items():
            assert img["camera_id"] == expected[iid], \
                "Image {}: camera_id={}, expected={}".format(
                    iid, img["camera_id"], expected[iid])

    def test_observation_counts_preserved(self):
        original = read_images_bin(
            os.path.join(ORIG_DIR, "images.bin"))
        repaired = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        for iid in original:
            assert iid in repaired, \
                "Image {} missing from repaired".format(iid)
            assert len(repaired[iid]["observations"]) == \
                len(original[iid]["observations"]), \
                "Image {}: observation count changed".format(iid)

    def test_image_names_preserved(self):
        original = read_images_bin(
            os.path.join(ORIG_DIR, "images.bin"))
        repaired = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        for iid in original:
            assert repaired[iid]["name"] == original[iid]["name"], \
                "Image {}: name changed".format(iid)


class TestPointCloud:
    def test_point_count_preserved(self):
        original = read_points3d_bin(
            os.path.join(ORIG_DIR, "points3D.bin"))
        repaired = read_points3d_bin(
            os.path.join(REPAIR_DIR, "points3D.bin"))
        assert len(repaired) == len(original), \
            "Point count: repaired={}, original={}".format(
                len(repaired), len(original))

    def test_no_orphan_track_references(self):
        images = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        points = read_points3d_bin(
            os.path.join(REPAIR_DIR, "points3D.bin"))
        valid_ids = set(images.keys())
        for pid, pt in points.items():
            for img_id, _ in pt["track"]:
                assert img_id in valid_ids, \
                    "Point {}: track references non-existent image {}".format(
                        pid, img_id)

    def test_point_positions_preserved(self):
        original = read_points3d_bin(
            os.path.join(ORIG_DIR, "points3D.bin"))
        repaired = read_points3d_bin(
            os.path.join(REPAIR_DIR, "points3D.bin"))
        for pid in original:
            assert pid in repaired, \
                "Point {} missing from repaired".format(pid)
            for i in range(3):
                assert abs(original[pid]["xyz"][i] -
                           repaired[pid]["xyz"][i]) < 1e-10, \
                    "Point {}: xyz[{}] changed".format(pid, i)

    def test_point_errors_preserved(self):
        original = read_points3d_bin(
            os.path.join(ORIG_DIR, "points3D.bin"))
        repaired = read_points3d_bin(
            os.path.join(REPAIR_DIR, "points3D.bin"))
        for pid in original:
            assert abs(original[pid]["error"] -
                       repaired[pid]["error"]) < 1e-10, \
                "Point {}: reprojection error changed".format(pid)

    def test_valid_tracks_retained(self):
        """Tracks should not lose entries that reference valid images
        and are geometrically valid (point in front of camera)."""
        original = read_points3d_bin(
            os.path.join(ORIG_DIR, "points3D.bin"))
        repaired_pts = read_points3d_bin(
            os.path.join(REPAIR_DIR, "points3D.bin"))
        repaired_imgs = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        valid_ids = set(repaired_imgs.keys())
        for pid in original:
            xyz = original[pid]["xyz"]
            orig_valid = []
            for img_id, pidx in original[pid]["track"]:
                if img_id not in valid_ids:
                    continue
                img = repaired_imgs[img_id]
                R = qvec2rotmat(img["qvec"])
                z_cam = sum(R[2][c] * xyz[c]
                            for c in range(3)) + img["tvec"][2]
                if z_cam > 0:
                    orig_valid.append((img_id, pidx))
            rep_track = repaired_pts[pid]["track"]
            assert len(rep_track) >= len(orig_valid), \
                "Point {}: valid track entries were lost".format(pid)


class TestGeometricConsistency:
    def test_no_behind_camera_tracks(self):
        """No track entry should reference an image where the
        3D point is behind the camera (negative z in camera space)."""
        images = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        points = read_points3d_bin(
            os.path.join(REPAIR_DIR, "points3D.bin"))
        for pid, pt in points.items():
            xyz = pt["xyz"]
            for img_id, _ in pt["track"]:
                img = images[img_id]
                R = qvec2rotmat(img["qvec"])
                z_cam = sum(R[2][c] * xyz[c]
                            for c in range(3)) + img["tvec"][2]
                assert z_cam > 0, \
                    "Point {} is behind camera in image {} " \
                    "(z_cam={:.4f})".format(pid, img_id, z_cam)


class TestSceneConfig:
    def test_config_exists(self):
        assert os.path.isfile(CONFIG_PATH), \
            "Scene config not found at {}".format(CONFIG_PATH)

    def test_config_structure(self):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert "normalization" in config, "Missing 'normalization'"
        assert "quality_metrics" in config, "Missing 'quality_metrics'"
        norm = config["normalization"]
        assert "center" in norm and "radius" in norm and "translate" in norm
        qm = config["quality_metrics"]
        for key in ["num_cameras", "num_images", "num_points",
                     "behind_camera_entries_removed",
                     "points_below_min_triangulation",
                     "median_triangulation_angle_deg",
                     "mean_track_length"]:
            assert key in qm, "Missing quality_metrics.{}".format(key)

    def test_normalization_center(self):
        """Center should be centroid of camera world positions."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        center = config["normalization"]["center"]
        assert len(center) == 3
        # Independently compute expected center from repaired images
        images = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        positions = [camera_world_pos(img["qvec"], img["tvec"])
                     for img in images.values()]
        n = len(positions)
        expected = [sum(p[i] for p in positions) / n for i in range(3)]
        for i in range(3):
            assert abs(center[i] - expected[i]) < 0.05, \
                "center[{}]={}, expected={}".format(
                    i, center[i], expected[i])

    def test_normalization_radius(self):
        """Radius should be 1.1x max distance from center to any camera."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        radius = config["normalization"]["radius"]
        center = config["normalization"]["center"]
        # Independently compute
        images = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        max_dist = 0.0
        for img in images.values():
            pos = camera_world_pos(img["qvec"], img["tvec"])
            dist = math.sqrt(sum(
                (pos[i] - center[i]) ** 2 for i in range(3)))
            max_dist = max(max_dist, dist)
        expected_radius = max_dist * 1.1
        assert abs(radius - expected_radius) < 0.1, \
            "radius={}, expected={}".format(radius, expected_radius)

    def test_normalization_translate(self):
        """Translate should be -center."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        center = config["normalization"]["center"]
        translate = config["normalization"]["translate"]
        for i in range(3):
            assert abs(translate[i] + center[i]) < 0.001, \
                "translate[{}]={}, expected -center={}".format(
                    i, translate[i], -center[i])

    def test_behind_camera_count(self):
        """Verify behind-camera entries were actually removed by
        comparing original and repaired track data."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        reported = config["quality_metrics"]["behind_camera_entries_removed"]
        # Also independently verify by comparing original vs repaired
        orig_pts = read_points3d_bin(
            os.path.join(ORIG_DIR, "points3D.bin"))
        rep_pts = read_points3d_bin(
            os.path.join(REPAIR_DIR, "points3D.bin"))
        rep_imgs = read_images_bin(
            os.path.join(REPAIR_DIR, "images.bin"))
        valid_ids = set(rep_imgs.keys())
        actual_removed = 0
        for pid in orig_pts:
            orig_valid_non_behind = 0
            for img_id, _ in orig_pts[pid]["track"]:
                if img_id not in valid_ids:
                    continue
                img = rep_imgs[img_id]
                R = qvec2rotmat(img["qvec"])
                z_cam = sum(R[2][c] * orig_pts[pid]["xyz"][c]
                            for c in range(3)) + img["tvec"][2]
                if z_cam <= 0:
                    actual_removed += 1
        assert actual_removed >= 4, \
            "Expected >= 4 behind-camera entries in original data, " \
            "found {}".format(actual_removed)
        assert reported >= 4, \
            "Expected >= 4 behind-camera entries removed (reported {}), " \
            "actual in data: {}".format(reported, actual_removed)

    def test_low_angle_count(self):
        """Verify low triangulation angle point count."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        count = config["quality_metrics"]["points_below_min_triangulation"]
        assert count >= 3, \
            "Expected >= 3 low-angle points, got {}".format(count)

    def test_median_triangulation_angle_reasonable(self):
        """Median triangulation angle for a well-formed scene
        should be well above the 2 degree minimum threshold."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        angle = config["quality_metrics"]["median_triangulation_angle_deg"]
        assert angle > 5.0, \
            "Median triangulation angle {}deg is suspiciously low".format(
                angle)
        assert angle < 180.0, \
            "Median triangulation angle {}deg is impossibly high".format(
                angle)


class TestDiagnosticReport:
    def test_report_exists(self):
        assert os.path.isfile(REPORT_PATH), \
            "Diagnostic report not found at {}".format(REPORT_PATH)

    def test_report_structure(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert "issues" in report, "Report missing 'issues'"
        assert "total_issues" in report, "Report missing 'total_issues'"
        assert isinstance(report["issues"], list)
        assert isinstance(report["total_issues"], int)

    def test_report_covers_issue_types(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        types = set()
        for issue in report["issues"]:
            assert "type" in issue, "Issue entry missing 'type' field"
            types.add(issue["type"])
        assert len(types) >= 4, \
            "Expected >=4 distinct issue types, found {}: {}".format(
                len(types), types)

    def test_report_issue_count(self):
        with open(REPORT_PATH) as f:
            report = json.load(f)
        assert report["total_issues"] >= 4, \
            "Expected >=4 issues, got {}".format(report["total_issues"])
