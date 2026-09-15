
import json
import os
import sqlite3
import struct
import math
import numpy as np
import pytest


DB_PATH = "/app/database.db"
REPORT_PATH = "/app/report.json"

# Camera model IDs per COLMAP enum
CAMERA_MODEL_IDS = {"SIMPLE_PINHOLE": 0, "SIMPLE_RADIAL": 2, "OPENCV": 4}

# Expected camera data: (camera_id, model_id, width, height, params_list)
EXPECTED_CAMERAS = [
    (1, 0, 1920, 1080, [1500.0, 960.0, 540.0]),
    (2, 2, 2048, 1536, [1800.0, 1024.0, 768.0, -0.05]),
    (3, 4, 1920, 1080, [1600.0, 1605.0, 955.0, 545.0, -0.03, 0.001, 0.0002, -0.0001]),
]

# Expected images: (image_id, name, camera_id, qw, qx, qy, qz, tx, ty, tz)
EXPECTED_IMAGES = [
    (1, "IMG_0001.jpg", 1, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    (2, "IMG_0002.jpg", 1, 0.9961947, 0.0, 0.0871557, 0.0, 0.5, 0.0, 0.1),
    (3, "IMG_0003.jpg", 2, 0.9914449, 0.1305262, 0.0, 0.0, -0.3, 0.2, 0.5),
    (4, "IMG_0004.jpg", 2, 0.9848078, 0.0, 0.0, 0.1736482, 0.8, -0.3, 0.2),
    (5, "IMG_0005.jpg", 3, 0.9238795, 0.0, 0.3826834, 0.0, 1.5, 0.3, -0.2),
    (6, "IMG_0006.jpg", 3, 0.9659258, 0.1830127, 0.0, 0.1830127, 0.0, 0.5, 1.0),
]

# Expected keypoints per image: {image_id: [(x, y), ...]}
EXPECTED_KEYPOINTS = {
    1: [(500.5, 300.2), (1200.3, 450.7), (800.1, 600.9), (1500.6, 200.4),
        (350.8, 800.3), (1100.2, 900.5), (960.0, 540.0), (1800.5, 100.3)],
    2: [(520.3, 310.5), (790.5, 620.1), (1350.2, 700.8), (370.1, 790.6),
        (1600.4, 350.2), (900.7, 480.3), (1100.0, 550.0)],
    3: [(600.2, 400.5), (1300.5, 550.3), (1450.8, 800.2), (700.3, 1100.6),
        (300.1, 700.4), (1800.6, 300.9), (1024.0, 1200.5), (850.3, 500.1),
        (1150.7, 950.8)],
    4: [(820.4, 650.3), (680.1, 1050.7), (1780.3, 350.6), (1150.5, 880.2),
        (400.6, 1300.1), (1200.8, 950.4)],
    5: [(1180.6, 430.2), (780.3, 580.5), (320.7, 750.1), (1580.2, 320.8),
        (1750.5, 280.4), (1000.1, 1050.3), (450.8, 900.6), (1100.4, 550.7)],
    6: [(1380.5, 680.3), (720.2, 1020.6), (340.8, 730.4), (1550.1, 350.7),
        (1130.6, 860.2), (940.3, 520.8)],
}

# Expected match counts per pair_id
# pair_id = 2147483647 * min(id1,id2) + max(id1,id2)
EXPECTED_PAIR_MATCHES = {
    2147483649: 3,   # (1,2): pts 1,3,7
    2147483650: 3,   # (1,3): pts 1,2,5
    2147483651: 3,   # (1,4): pts 3,5,10
    2147483652: 2,   # (1,5): pts 2,3
    2147483653: 3,   # (1,6): pts 5,10,14
    4294967297: 4,   # (2,3): pts 1,4,12,15
    4294967298: 2,   # (2,4): pts 3,15
    4294967299: 3,   # (2,5): pts 3,8,15
    4294967300: 2,   # (2,6): pts 4,8
    6442450945: 3,   # (3,4): pts 5,9,15
    6442450946: 5,   # (3,5): pts 2,6,9,11,15
    6442450947: 3,   # (3,6): pts 4,5,6
    8589934593: 4,   # (4,5): pts 3,9,13,15
    8589934594: 2,   # (4,6): pts 5,10
    10737418241: 2,  # (5,6): pts 6,8
}

# Expected specific match index pairs for selected pairs
EXPECTED_MATCH_INDICES = {
    # pair (1,2): pt1->(0,0), pt3->(2,1), pt7->(4,3)
    2147483649: {(0, 0), (2, 1), (4, 3)},
    # pair (3,5): pt2->(1,0), pt6->(4,2), pt9->(5,4), pt11->(6,5), pt15->(8,7)
    6442450946: {(1, 0), (4, 2), (5, 4), (6, 5), (8, 7)},
    # pair (4,5): pt3->(0,1), pt9->(2,4), pt13->(4,6), pt15->(5,7)
    8589934593: {(0, 1), (2, 4), (4, 6), (5, 7)},
}

EXPECTED_TRACK_HISTOGRAM = {"2": 5, "3": 7, "4": 3}


def quat_to_rotmat(qw, qx, qy, qz):
    """Convert Hamilton quaternion to 3x3 rotation matrix."""
    R = np.array([
        [1 - 2*(qy*qy + qz*qz), 2*(qx*qy - qw*qz), 2*(qx*qz + qw*qy)],
        [2*(qx*qy + qw*qz), 1 - 2*(qx*qx + qz*qz), 2*(qy*qz - qw*qx)],
        [2*(qx*qz - qw*qy), 2*(qy*qz + qw*qx), 1 - 2*(qx*qx + qy*qy)],
    ])
    return R


def compute_expected_camera_centers():
    """Compute expected camera centers as -R^T * T for each image."""
    centers = {}
    for img in EXPECTED_IMAGES:
        img_id, _, _, qw, qx, qy, qz, tx, ty, tz = img
        R = quat_to_rotmat(qw, qx, qy, qz)
        T = np.array([tx, ty, tz])
        center = -R.T @ T
        centers[str(img_id)] = center.tolist()
    return centers


# ------- Tests -------

class TestDatabaseExists:
    def test_database_file_exists(self):
        assert os.path.isfile(DB_PATH), f"Database not found at {DB_PATH}"

    def test_report_file_exists(self):
        assert os.path.isfile(REPORT_PATH), f"Report not found at {REPORT_PATH}"


class TestDatabaseSchema:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cur = self.conn.cursor()
        yield
        self.conn.close()

    def test_cameras_table_exists(self):
        self.cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cameras'")
        assert self.cur.fetchone() is not None

    def test_images_table_exists(self):
        self.cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='images'")
        assert self.cur.fetchone() is not None

    def test_keypoints_table_exists(self):
        self.cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='keypoints'")
        assert self.cur.fetchone() is not None

    def test_descriptors_table_exists(self):
        self.cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='descriptors'")
        assert self.cur.fetchone() is not None

    def test_matches_table_exists(self):
        self.cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='matches'")
        assert self.cur.fetchone() is not None

    def test_two_view_geometries_table_exists(self):
        self.cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='two_view_geometries'")
        assert self.cur.fetchone() is not None


class TestCamerasTable:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cur = self.conn.cursor()
        yield
        self.conn.close()

    def test_camera_count(self):
        self.cur.execute("SELECT COUNT(*) FROM cameras")
        assert self.cur.fetchone()[0] == 3

    @pytest.mark.parametrize("cam_id,model_id,width,height,params", EXPECTED_CAMERAS)
    def test_camera_metadata(self, cam_id, model_id, width, height, params):
        self.cur.execute(
            "SELECT model, width, height FROM cameras WHERE camera_id=?", (cam_id,)
        )
        row = self.cur.fetchone()
        assert row is not None, f"Camera {cam_id} not found"
        assert row[0] == model_id, f"Camera {cam_id}: expected model {model_id}, got {row[0]}"
        assert row[1] == width
        assert row[2] == height

    @pytest.mark.parametrize("cam_id,model_id,width,height,params", EXPECTED_CAMERAS)
    def test_camera_params_blob(self, cam_id, model_id, width, height, params):
        self.cur.execute("SELECT params FROM cameras WHERE camera_id=?", (cam_id,))
        row = self.cur.fetchone()
        assert row is not None
        blob = row[0]
        assert blob is not None, f"Camera {cam_id}: params blob is NULL"
        n_params = len(params)
        expected_size = n_params * 8  # float64 = 8 bytes
        assert len(blob) == expected_size, (
            f"Camera {cam_id}: expected {expected_size} bytes, got {len(blob)}"
        )
        decoded = struct.unpack(f"<{n_params}d", blob)
        for i, (expected, actual) in enumerate(zip(params, decoded)):
            assert abs(expected - actual) < 1e-10, (
                f"Camera {cam_id} param[{i}]: expected {expected}, got {actual}"
            )


class TestImagesTable:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cur = self.conn.cursor()
        yield
        self.conn.close()

    def test_image_count(self):
        self.cur.execute("SELECT COUNT(*) FROM images")
        assert self.cur.fetchone()[0] == 6

    @pytest.mark.parametrize(
        "img_id,name,cam_id,qw,qx,qy,qz,tx,ty,tz", EXPECTED_IMAGES
    )
    def test_image_entry(self, img_id, name, cam_id, qw, qx, qy, qz, tx, ty, tz):
        self.cur.execute(
            "SELECT name, camera_id FROM images WHERE image_id=?", (img_id,)
        )
        row = self.cur.fetchone()
        assert row is not None, f"Image {img_id} not found"
        assert row[0] == name
        assert row[1] == cam_id


class TestKeypointsTable:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cur = self.conn.cursor()
        yield
        self.conn.close()

    def test_keypoints_count(self):
        self.cur.execute("SELECT COUNT(*) FROM keypoints")
        assert self.cur.fetchone()[0] == 6

    @pytest.mark.parametrize("image_id", [1, 2, 3, 4, 5, 6])
    def test_keypoints_data(self, image_id):
        self.cur.execute(
            "SELECT rows, cols, data FROM keypoints WHERE image_id=?", (image_id,)
        )
        row = self.cur.fetchone()
        assert row is not None, f"Keypoints for image {image_id} not found"
        n_rows, n_cols, blob = row
        expected_kps = EXPECTED_KEYPOINTS[image_id]
        assert n_rows == len(expected_kps), (
            f"Image {image_id}: expected {len(expected_kps)} keypoints, got {n_rows}"
        )
        assert n_cols == 2
        decoded = struct.unpack(f"<{n_rows * 2}f", blob)
        for i, (ex, ey) in enumerate(expected_kps):
            ax, ay = decoded[2 * i], decoded[2 * i + 1]
            assert abs(ex - ax) < 0.1, (
                f"Image {image_id} kp[{i}].x: expected {ex}, got {ax}"
            )
            assert abs(ey - ay) < 0.1, (
                f"Image {image_id} kp[{i}].y: expected {ey}, got {ay}"
            )


class TestMatchesTable:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.cur = self.conn.cursor()
        yield
        self.conn.close()

    def test_matches_count(self):
        self.cur.execute("SELECT COUNT(*) FROM matches")
        count = self.cur.fetchone()[0]
        assert count == 15, f"Expected 15 match pairs, got {count}"

    def test_all_pair_ids_present(self):
        self.cur.execute("SELECT pair_id FROM matches")
        pair_ids = {row[0] for row in self.cur.fetchall()}
        for expected_pid in EXPECTED_PAIR_MATCHES:
            assert expected_pid in pair_ids, (
                f"pair_id {expected_pid} not found in matches table"
            )

    @pytest.mark.parametrize(
        "pair_id,expected_count", list(EXPECTED_PAIR_MATCHES.items())
    )
    def test_match_row_count(self, pair_id, expected_count):
        self.cur.execute(
            "SELECT rows, cols FROM matches WHERE pair_id=?", (pair_id,)
        )
        row = self.cur.fetchone()
        assert row is not None, f"pair_id {pair_id} not found"
        n_rows, n_cols = row
        assert n_cols == 2, f"pair_id {pair_id}: cols should be 2, got {n_cols}"
        assert n_rows == expected_count, (
            f"pair_id {pair_id}: expected {expected_count} matches, got {n_rows}"
        )

    @pytest.mark.parametrize(
        "pair_id,expected_indices", list(EXPECTED_MATCH_INDICES.items())
    )
    def test_match_indices(self, pair_id, expected_indices):
        self.cur.execute(
            "SELECT rows, cols, data FROM matches WHERE pair_id=?", (pair_id,)
        )
        row = self.cur.fetchone()
        assert row is not None
        n_rows, n_cols, blob = row
        decoded = struct.unpack(f"<{n_rows * 2}I", blob)
        actual_indices = set()
        for i in range(n_rows):
            actual_indices.add((decoded[2 * i], decoded[2 * i + 1]))
        assert actual_indices == expected_indices, (
            f"pair_id {pair_id}: match indices mismatch.\n"
            f"Expected: {sorted(expected_indices)}\n"
            f"Got: {sorted(actual_indices)}"
        )


class TestReportCameraCenters:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def test_camera_centers_key_exists(self):
        assert "camera_centers" in self.report

    def test_camera_centers_count(self):
        assert len(self.report["camera_centers"]) == 6

    @pytest.mark.parametrize("image_id", ["1", "2", "3", "4", "5", "6"])
    def test_camera_center_values(self, image_id):
        expected_centers = compute_expected_camera_centers()
        center = self.report["camera_centers"][image_id]
        expected = expected_centers[image_id]
        for i, (e, a) in enumerate(zip(expected, center)):
            assert abs(e - a) < 1e-4, (
                f"Image {image_id} center[{i}]: expected {e:.6f}, got {a:.6f}"
            )


class TestReportPairMatches:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def test_pair_matches_key_exists(self):
        assert "pair_matches" in self.report

    def test_pair_matches_count(self):
        assert len(self.report["pair_matches"]) == 15

    @pytest.mark.parametrize(
        "pair_id,expected_count", list(EXPECTED_PAIR_MATCHES.items())
    )
    def test_pair_match_value(self, pair_id, expected_count):
        pid_str = str(pair_id)
        assert pid_str in self.report["pair_matches"], (
            f"pair_id {pid_str} not in report pair_matches"
        )
        actual = self.report["pair_matches"][pid_str]
        assert actual == expected_count, (
            f"pair_id {pid_str}: expected {expected_count}, got {actual}"
        )


class TestReportTrackHistogram:
    @pytest.fixture(autouse=True)
    def setup(self):
        with open(REPORT_PATH) as f:
            self.report = json.load(f)

    def test_track_histogram_key_exists(self):
        assert "track_length_histogram" in self.report

    def test_track_histogram_values(self):
        hist = self.report["track_length_histogram"]
        for length_str, expected_count in EXPECTED_TRACK_HISTOGRAM.items():
            assert length_str in hist, (
                f"Track length {length_str} not in histogram"
            )
            assert hist[length_str] == expected_count, (
                f"Track length {length_str}: expected {expected_count}, got {hist[length_str]}"
            )
