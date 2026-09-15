"""
"""
import csv
import json
import os
import sqlite3
import subprocess

import pytest

SCORER_PATH = "/app/scorer.py"
OUTPUT_DIR = "/app/output"


def run_scorer(config_path, output_dir):
    """Run the scorer as a subprocess and assert success."""
    cmd = [
        "python3", SCORER_PATH,
        "--config", config_path,
        "--output-dir", output_dir,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (
        f"Scorer failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def create_eval_db(db_path, videos, activity_types, annotators, annotations):
    """Create a SQLite evaluation database with multi-annotator schema."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE videos ("
        "id INTEGER PRIMARY KEY, filename TEXT NOT NULL UNIQUE, num_frames INTEGER NOT NULL)"
    )
    c.execute(
        "CREATE TABLE activity_types ("
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)"
    )
    c.execute(
        "CREATE TABLE annotators ("
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE)"
    )
    c.execute(
        "CREATE TABLE reference_annotations ("
        "id INTEGER PRIMARY KEY, activity_type_id INTEGER NOT NULL, "
        "video_id INTEGER NOT NULL, annotator_id INTEGER NOT NULL, "
        "start_frame INTEGER NOT NULL, end_frame INTEGER NOT NULL)"
    )
    for v in videos:
        c.execute("INSERT INTO videos VALUES (?, ?, ?)", v)
    for a in activity_types:
        c.execute("INSERT INTO activity_types VALUES (?, ?)", a)
    for ann in annotators:
        c.execute("INSERT INTO annotators VALUES (?, ?)", ann)
    for ref in annotations:
        c.execute("INSERT INTO reference_annotations VALUES (?, ?, ?, ?, ?, ?)", ref)
    conn.commit()
    conn.close()


def create_detections_jsonl(jsonl_path, detections):
    """Write detections in JSONL format."""
    with open(jsonl_path, "w") as f:
        for det in detections:
            f.write(json.dumps(det) + "\n")


def create_config_toml(toml_path, db_path, jsonl_path, **kwargs):
    """Write a TOML config file with consensus and decision cost parameters."""
    alignment_mode = kwargs.get("alignment_mode", "iou")
    iou_threshold = kwargs.get("iou_threshold", 0.2)
    collar_frames = kwargs.get("collar_frames", 30)
    pfa_max = kwargs.get("pfa_max", 0.2)
    consensus_enabled = kwargs.get("consensus_enabled", True)
    consensus_iou_threshold = kwargs.get("consensus_iou_threshold", 0.5)
    include_singletons = kwargs.get("include_singletons", False)
    c_miss = kwargs.get("c_miss", 1.0)
    c_fa = kwargs.get("c_fa", 1.0)
    p_target = kwargs.get("p_target", 0.5)

    enabled_str = "true" if consensus_enabled else "false"
    singletons_str = "true" if include_singletons else "false"

    with open(toml_path, "w") as f:
        f.write(f'[evaluation]\nalignment_mode = "{alignment_mode}"\n')
        f.write(f"iou_threshold = {iou_threshold}\n")
        f.write(f"collar_frames = {collar_frames}\npfa_max = {pfa_max}\n\n")
        f.write(f"[consensus]\nenabled = {enabled_str}\n")
        f.write(f"consensus_iou_threshold = {consensus_iou_threshold}\n")
        f.write(f"include_singletons = {singletons_str}\n\n")
        f.write(f"[decision_cost]\nc_miss = {c_miss}\nc_fa = {c_fa}\n")
        f.write(f"p_target = {p_target}\n\n")
        f.write(f'[data]\ndatabase = "{db_path}"\ndetections = "{jsonl_path}"\n')


# ---------------------------------------------------------------------------
# Primary dataset tests (IoU mode, multi-annotator consensus)
# ---------------------------------------------------------------------------
# Total frames = 3000 + 4500 = 7500
#
# Consensus results (consensus_iou_threshold=0.5, include_singletons=false):
#   PersonRuns: 3 cons refs
#     (120,280,v1) w=161, (810,1090,v1) w=281, (250,550,v2) w=301
#   Closing: 3 cons refs
#     (1510,1790,v1) w=281, (1050,1350,v2) w=301, (3200,3500,v2) w=301
#   Opening: 1 cons ref (v2[2000,2300] is singleton → excluded)
#     (520,680,v1) w=161
#
# PersonRuns (n_ref=3, n_sys=4): all 3 matched → nAUDC=0, MinNDCF=0
# Closing (n_ref=3, n_sys=3): 2 matched, 1 FN, 1 FP
#   nAUDC=1/3, MinNDCF=1/3
#   tw: matched w=281+301=582, missed w=301, total=883 → tw_nAUDC=301/883
# Opening (n_ref=1, n_sys=0): nAUDC=1, MinNDCF=1
# ---------------------------------------------------------------------------


class TestPrimaryDataset:
    """Tests on the main evaluation dataset shipped with the task."""

    @pytest.fixture(autouse=True)
    def setup(self):
        run_scorer("/app/eval_config.toml", OUTPUT_DIR)

    def _read_activity_csv(self):
        with open(os.path.join(OUTPUT_DIR, "scores_by_activity.csv")) as f:
            reader = csv.DictReader(f)
            return {row["activity"]: row for row in reader}

    def _read_aggregated_csv(self):
        with open(os.path.join(OUTPUT_DIR, "scores_aggregated.csv")) as f:
            reader = csv.DictReader(f)
            return {row["metric"]: row for row in reader}

    # -- File existence --

    def test_output_files_exist(self):
        for fname in ("scores_by_activity.csv", "scores_aggregated.csv", "det_curves.json"):
            assert os.path.isfile(os.path.join(OUTPUT_DIR, fname)), f"Missing {fname}"

    # -- PersonRuns metrics --

    def test_personruns_naudc(self):
        rows = self._read_activity_csv()
        assert "PersonRuns" in rows
        assert abs(float(rows["PersonRuns"]["nAUDC"])) < 1e-4

    def test_personruns_audc(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["PersonRuns"]["AUDC"])) < 1e-6

    def test_personruns_counts(self):
        rows = self._read_activity_csv()
        assert int(rows["PersonRuns"]["n_ref"]) == 3
        assert int(rows["PersonRuns"]["n_sys"]) == 4

    def test_personruns_tw_naudc(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["PersonRuns"]["tw_nAUDC"])) < 1e-4

    def test_personruns_min_ndcf(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["PersonRuns"]["MinNDCF"])) < 1e-4

    # -- Closing metrics --

    def test_closing_naudc(self):
        rows = self._read_activity_csv()
        assert "Closing" in rows
        assert abs(float(rows["Closing"]["nAUDC"]) - 1.0 / 3.0) < 1e-4

    def test_closing_audc(self):
        rows = self._read_activity_csv()
        expected_audc = (1.0 / 3.0) * 0.2
        assert abs(float(rows["Closing"]["AUDC"]) - expected_audc) < 1e-5

    def test_closing_counts(self):
        rows = self._read_activity_csv()
        assert int(rows["Closing"]["n_ref"]) == 3
        assert int(rows["Closing"]["n_sys"]) == 3

    def test_closing_tw_naudc(self):
        rows = self._read_activity_csv()
        expected = 301.0 / 883.0
        assert abs(float(rows["Closing"]["tw_nAUDC"]) - expected) < 1e-3

    def test_closing_tw_audc(self):
        rows = self._read_activity_csv()
        expected = (301.0 / 883.0) * 0.2
        assert abs(float(rows["Closing"]["tw_AUDC"]) - expected) < 1e-4

    def test_closing_min_ndcf(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["Closing"]["MinNDCF"]) - 1.0 / 3.0) < 1e-4

    # -- Opening metrics --

    def test_opening_naudc(self):
        rows = self._read_activity_csv()
        assert "Opening" in rows
        assert abs(float(rows["Opening"]["nAUDC"]) - 1.0) < 1e-4

    def test_opening_audc(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["Opening"]["AUDC"]) - 0.2) < 1e-5

    def test_opening_counts(self):
        rows = self._read_activity_csv()
        assert int(rows["Opening"]["n_ref"]) == 1
        assert int(rows["Opening"]["n_sys"]) == 0

    def test_opening_tw_naudc(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["Opening"]["tw_nAUDC"]) - 1.0) < 1e-4

    def test_opening_min_ndcf(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["Opening"]["MinNDCF"]) - 1.0) < 1e-4

    # -- Aggregated metrics --

    def test_mean_naudc(self):
        rows = self._read_aggregated_csv()
        assert "mean_nAUDC" in rows
        expected = 4.0 / 9.0
        assert abs(float(rows["mean_nAUDC"]["value"]) - expected) < 1e-4

    def test_weighted_mean_naudc(self):
        rows = self._read_aggregated_csv()
        assert "weighted_mean_nAUDC" in rows
        expected = 2.0 / 7.0
        assert abs(float(rows["weighted_mean_nAUDC"]["value"]) - expected) < 1e-4

    def test_mean_tw_naudc(self):
        rows = self._read_aggregated_csv()
        assert "mean_tw_nAUDC" in rows
        expected = (0.0 + 301.0 / 883.0 + 1.0) / 3.0
        assert abs(float(rows["mean_tw_nAUDC"]["value"]) - expected) < 1e-3

    def test_mean_min_ndcf(self):
        rows = self._read_aggregated_csv()
        assert "mean_MinNDCF" in rows
        expected = 4.0 / 9.0
        assert abs(float(rows["mean_MinNDCF"]["value"]) - expected) < 1e-4

    # -- DET curve structure and values --

    def test_det_curves_structure(self):
        with open(os.path.join(OUTPUT_DIR, "det_curves.json")) as f:
            curves = json.load(f)
        assert set(curves.keys()) == {"PersonRuns", "Closing", "Opening"}
        for activity, data in curves.items():
            assert "points" in data
            points = data["points"]
            assert len(points) >= 2, f"{activity} DET curve too short"
            for pt in points:
                assert len(pt) == 2
                assert 0.0 <= pt[0] <= 1.0, f"Pfa out of range: {pt[0]}"
                assert 0.0 <= pt[1] <= 1.0, f"Pmiss out of range: {pt[1]}"

    def test_det_curve_personruns(self):
        with open(os.path.join(OUTPUT_DIR, "det_curves.json")) as f:
            curves = json.load(f)
        pts = curves["PersonRuns"]["points"]
        # (0,1) (0,2/3) (0,1/3) (0,0) (1/7500,0) (0.2,0) — 6 points
        assert len(pts) == 6
        assert abs(pts[0][0]) < 1e-6 and abs(pts[0][1] - 1.0) < 1e-6
        assert abs(pts[-1][0] - 0.2) < 1e-4 and abs(pts[-1][1]) < 1e-6

    def test_det_curve_closing(self):
        with open(os.path.join(OUTPUT_DIR, "det_curves.json")) as f:
            curves = json.load(f)
        pts = curves["Closing"]["points"]
        # (0,1) (0,2/3) (0,1/3) (1/7500,1/3) (0.2,1/3) — 5 points
        assert len(pts) == 5
        assert abs(pts[0][0]) < 1e-6 and abs(pts[0][1] - 1.0) < 1e-6
        assert abs(pts[-1][0] - 0.2) < 1e-4
        assert abs(pts[-1][1] - 1.0 / 3.0) < 1e-4

    def test_det_curve_opening(self):
        with open(os.path.join(OUTPUT_DIR, "det_curves.json")) as f:
            curves = json.load(f)
        pts = curves["Opening"]["points"]
        assert len(pts) == 2
        assert abs(pts[0][0]) < 1e-6 and abs(pts[0][1] - 1.0) < 1e-6
        assert abs(pts[1][0] - 0.2) < 1e-4 and abs(pts[1][1] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Secondary dataset: collar alignment mode — prevents hardcoding
# ---------------------------------------------------------------------------
# Single video, 500 frames. Collar mode with collar_frames=10.
# Consensus threshold=0.4, include_singletons=false.
#
# Jump: 2 consensus refs (55,95) w=41, (305,345) w=41
#   Dets: (180,240,0.9)→FP, (52,98,0.7)→TP(Ref1), (295,355,0.3)→TP(Ref2)
#   DET: (0,1) (0.002,1) (0.002,0.5) (0.002,0) (0.2,0)
#   AUDC=0.002, nAUDC=0.01
#   MinDCF=0.001, MinNDCF=0.002 (differs from nAUDC)
#
# Slide: 1 consensus ref (205,245) w=41, no detections
#   nAUDC=1.0, MinNDCF=1.0
# ---------------------------------------------------------------------------


class TestSecondaryDataset:
    """Test with collar mode and programmatically generated data."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.out_dir = str(tmp_path / "output")

        db_path = str(tmp_path / "eval.db")
        create_eval_db(
            db_path,
            videos=[(1, "test_v.mp4", 500)],
            activity_types=[(1, "Jump"), (2, "Slide")],
            annotators=[(1, "A"), (2, "B")],
            annotations=[
                # Jump: annotator A
                (1, 1, 1, 1, 50, 100),
                (2, 1, 1, 1, 300, 350),
                # Jump: annotator B
                (3, 1, 1, 2, 55, 95),
                (4, 1, 1, 2, 305, 345),
                # Slide: annotator A
                (5, 2, 1, 1, 200, 250),
                # Slide: annotator B
                (6, 2, 1, 2, 205, 245),
            ],
        )

        jsonl_path = str(tmp_path / "dets.jsonl")
        create_detections_jsonl(jsonl_path, [
            {"activity": "Jump", "video": "test_v.mp4", "start": 180, "end": 240, "score": 0.9},
            {"activity": "Jump", "video": "test_v.mp4", "start": 52, "end": 98, "score": 0.7},
            {"activity": "Jump", "video": "test_v.mp4", "start": 295, "end": 355, "score": 0.3},
        ])

        toml_path = str(tmp_path / "config.toml")
        create_config_toml(
            toml_path, db_path, jsonl_path,
            alignment_mode="collar",
            collar_frames=10,
            consensus_iou_threshold=0.4,
        )

        run_scorer(toml_path, self.out_dir)

    def _read_activity_csv(self):
        with open(os.path.join(self.out_dir, "scores_by_activity.csv")) as f:
            reader = csv.DictReader(f)
            return {row["activity"]: row for row in reader}

    def _read_aggregated_csv(self):
        with open(os.path.join(self.out_dir, "scores_aggregated.csv")) as f:
            reader = csv.DictReader(f)
            return {row["metric"]: row for row in reader}

    def test_jump_naudc(self):
        rows = self._read_activity_csv()
        assert "Jump" in rows
        assert abs(float(rows["Jump"]["nAUDC"]) - 0.01) < 1e-4

    def test_jump_audc(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["Jump"]["AUDC"]) - 0.002) < 1e-5

    def test_jump_counts(self):
        rows = self._read_activity_csv()
        assert int(rows["Jump"]["n_ref"]) == 2
        assert int(rows["Jump"]["n_sys"]) == 3

    def test_jump_tw_naudc(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["Jump"]["tw_nAUDC"]) - 0.01) < 1e-4

    def test_jump_min_ndcf(self):
        """MinNDCF should differ from nAUDC due to interleaved FP/TP ordering."""
        rows = self._read_activity_csv()
        assert abs(float(rows["Jump"]["MinNDCF"]) - 0.002) < 1e-4

    def test_slide_naudc(self):
        rows = self._read_activity_csv()
        assert "Slide" in rows
        assert abs(float(rows["Slide"]["nAUDC"]) - 1.0) < 1e-4

    def test_slide_min_ndcf(self):
        rows = self._read_activity_csv()
        assert abs(float(rows["Slide"]["MinNDCF"]) - 1.0) < 1e-4

    def test_slide_counts(self):
        rows = self._read_activity_csv()
        assert int(rows["Slide"]["n_ref"]) == 1
        assert int(rows["Slide"]["n_sys"]) == 0

    def test_mean_naudc(self):
        rows = self._read_aggregated_csv()
        assert abs(float(rows["mean_nAUDC"]["value"]) - 0.505) < 1e-3

    def test_mean_min_ndcf(self):
        rows = self._read_aggregated_csv()
        assert abs(float(rows["mean_MinNDCF"]["value"]) - 0.501) < 1e-3

    def test_weighted_mean_naudc(self):
        rows = self._read_aggregated_csv()
        expected = (0.01 * 2 + 1.0 * 1) / 3.0
        assert abs(float(rows["weighted_mean_nAUDC"]["value"]) - expected) < 1e-3

    def test_jump_det_curve(self):
        with open(os.path.join(self.out_dir, "det_curves.json")) as f:
            curves = json.load(f)
        assert "Jump" in curves
        pts = curves["Jump"]["points"]
        # (0,1) (0.002,1) (0.002,0.5) (0.002,0) (0.2,0)
        assert len(pts) == 5
        assert abs(pts[0][0]) < 1e-6 and abs(pts[0][1] - 1.0) < 1e-6
        assert abs(pts[1][0] - 0.002) < 1e-5 and abs(pts[1][1] - 1.0) < 1e-6
        assert abs(pts[2][0] - 0.002) < 1e-5 and abs(pts[2][1] - 0.5) < 1e-4
        assert abs(pts[3][0] - 0.002) < 1e-5 and abs(pts[3][1]) < 1e-4
        assert abs(pts[4][0] - 0.2) < 1e-4 and abs(pts[4][1]) < 1e-4


# ---------------------------------------------------------------------------
# Edge case: IoU threshold affects matching on consensus-merged refs
# ---------------------------------------------------------------------------


class TestIoUThresholdEdge:
    """Verify that IoU threshold correctly affects matching after consensus."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.tmp = tmp_path

        # Both annotators agree exactly: R_A1=(100,200), R_A2=(100,200)
        # Consensus: IoU=1.0 → merge → consensus ref = (100,200)
        # Detection: (150,300) → IoU with (100,200) = 51/201 ≈ 0.2537
        db_path = str(tmp_path / "eval.db")
        create_eval_db(
            db_path,
            videos=[(1, "v.mp4", 500)],
            activity_types=[(1, "Act")],
            annotators=[(1, "a1"), (2, "a2")],
            annotations=[
                (1, 1, 1, 1, 100, 200),
                (2, 1, 1, 2, 100, 200),
            ],
        )

        jsonl_path = str(tmp_path / "dets.jsonl")
        create_detections_jsonl(jsonl_path, [
            {"activity": "Act", "video": "v.mp4", "start": 150, "end": 300, "score": 0.9},
        ])

        self.db_path = db_path
        self.jsonl_path = jsonl_path

    def _make_config(self, iou_threshold):
        toml_path = str(self.tmp / f"config_{iou_threshold}.toml")
        create_config_toml(
            toml_path, self.db_path, self.jsonl_path,
            iou_threshold=iou_threshold,
        )
        return toml_path

    def test_matched_at_low_threshold(self):
        """IoU ~0.254 >= 0.2 threshold -> matched -> nAUDC ≈ 0."""
        out = str(self.tmp / "out_low")
        config = self._make_config(0.2)
        run_scorer(config, out)
        with open(os.path.join(out, "scores_by_activity.csv")) as f:
            rows = {r["activity"]: r for r in csv.DictReader(f)}
        assert abs(float(rows["Act"]["nAUDC"])) < 1e-4
        assert abs(float(rows["Act"]["MinNDCF"])) < 1e-4

    def test_unmatched_at_high_threshold(self):
        """IoU ~0.254 < 0.5 threshold -> unmatched -> nAUDC=1, MinNDCF=1."""
        out = str(self.tmp / "out_high")
        config = self._make_config(0.5)
        run_scorer(config, out)
        with open(os.path.join(out, "scores_by_activity.csv")) as f:
            rows = {r["activity"]: r for r in csv.DictReader(f)}
        assert abs(float(rows["Act"]["nAUDC"]) - 1.0) < 1e-4
        assert abs(float(rows["Act"]["MinNDCF"]) - 1.0) < 1e-4
