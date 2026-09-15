"""
Tests for the IDRiD evaluation framework.

"""

import json
import os
import subprocess
import tempfile
import csv
import shutil

import numpy as np
from PIL import Image
import pytest


EVAL_SCRIPT = "/app/src/evaluate.py"
GEN_SCRIPT = "/app/src/generate_synthetic.py"


def run_cmd(args, expect_fail=False, timeout=120):
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout
    )
    if not expect_fail:
        assert result.returncode == 0, (
            f"Command failed: {' '.join(args)}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.returncode, result.stdout, result.stderr


def load_json(path):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# CLI basics
# ---------------------------------------------------------------------------
class TestCLIBasics:
    def test_evaluate_script_exists(self):
        assert os.path.isfile(EVAL_SCRIPT), f"{EVAL_SCRIPT} not found"

    def test_generate_script_exists(self):
        assert os.path.isfile(GEN_SCRIPT), f"{GEN_SCRIPT} not found"

    def test_evaluate_help(self):
        rc, _, _ = run_cmd(["python3", EVAL_SCRIPT, "--help"], expect_fail=True)
        assert rc in (0, 1, 2)

    def test_generate_help(self):
        rc, _, _ = run_cmd(["python3", GEN_SCRIPT, "--help"], expect_fail=True)
        assert rc in (0, 1, 2)

    def test_makefile_exists(self):
        assert os.path.isfile("/app/Makefile"), "/app/Makefile not found"


# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------
class TestSyntheticGenerator:
    def test_generate_segmentation(self, tmp_path):
        outdir = str(tmp_path / "seg")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "lesion_segmentation",
            "--num-images", "5",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.0",
        ])
        assert os.path.isdir(os.path.join(outdir, "gt"))
        assert os.path.isdir(os.path.join(outdir, "pred"))
        gt_files = os.listdir(os.path.join(outdir, "gt"))
        pred_files = os.listdir(os.path.join(outdir, "pred"))
        assert len(gt_files) > 0
        assert len(pred_files) > 0
        for f in gt_files:
            img = Image.open(os.path.join(outdir, "gt", f))
            assert img.mode in ("L", "1", "P"), f"GT mask {f} should be grayscale"

    def test_generate_grading(self, tmp_path):
        outdir = str(tmp_path / "grade")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "disease_grading",
            "--num-images", "20",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.0",
        ])
        assert os.path.isfile(os.path.join(outdir, "gt.csv"))
        assert os.path.isfile(os.path.join(outdir, "pred.csv"))

    def test_generate_localization(self, tmp_path):
        outdir = str(tmp_path / "loc")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "localization",
            "--num-images", "20",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.0",
        ])
        assert os.path.isfile(os.path.join(outdir, "gt.csv"))
        assert os.path.isfile(os.path.join(outdir, "pred.csv"))

    def test_deterministic_seeding(self, tmp_path):
        dir1 = str(tmp_path / "run1")
        dir2 = str(tmp_path / "run2")
        for d in (dir1, dir2):
            run_cmd([
                "python3", GEN_SCRIPT,
                "--task", "disease_grading",
                "--num-images", "10",
                "--output-dir", d,
                "--seed", "99",
                "--noise-level", "0.3",
            ])
        with open(os.path.join(dir1, "gt.csv")) as f1, \
             open(os.path.join(dir2, "gt.csv")) as f2:
            assert f1.read() == f2.read()
        with open(os.path.join(dir1, "pred.csv")) as f1, \
             open(os.path.join(dir2, "pred.csv")) as f2:
            assert f1.read() == f2.read()

    def test_segmentation_deterministic(self, tmp_path):
        dir1 = str(tmp_path / "seg1")
        dir2 = str(tmp_path / "seg2")
        for d in (dir1, dir2):
            run_cmd([
                "python3", GEN_SCRIPT,
                "--task", "lesion_segmentation",
                "--num-images", "3",
                "--output-dir", d,
                "--seed", "77",
                "--noise-level", "0.1",
            ])
        gt1_files = sorted(os.listdir(os.path.join(dir1, "gt")))
        gt2_files = sorted(os.listdir(os.path.join(dir2, "gt")))
        assert gt1_files == gt2_files
        for f in gt1_files:
            img1 = np.array(Image.open(os.path.join(dir1, "gt", f)))
            img2 = np.array(Image.open(os.path.join(dir2, "gt", f)))
            np.testing.assert_array_equal(img1, img2)

    def test_segmentation_multiblob(self, tmp_path):
        outdir = str(tmp_path / "blob_check")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "lesion_segmentation",
            "--num-images", "5",
            "--output-dir", outdir,
            "--seed", "123",
            "--noise-level", "0.0",
        ])
        gt_dir = os.path.join(outdir, "gt")
        found_multiblob = False
        for f in os.listdir(gt_dir):
            img = np.array(Image.open(os.path.join(gt_dir, f)))
            binary = (img > 127).astype(np.uint8)
            if binary.sum() == 0:
                continue
            rows = np.any(binary, axis=1)
            cols = np.any(binary, axis=0)
            row_indices = np.where(rows)[0]
            col_indices = np.where(cols)[0]
            if len(row_indices) == 0:
                continue
            bbox_area = (row_indices[-1] - row_indices[0] + 1) * \
                        (col_indices[-1] - col_indices[0] + 1)
            fill_ratio = binary.sum() / bbox_area if bbox_area > 0 else 1.0
            if fill_ratio < 0.95:
                found_multiblob = True
                break
        assert found_multiblob, \
            "Generated masks should contain multi-region blobs, not single rectangles"


# ---------------------------------------------------------------------------
# Lesion segmentation scoring
# ---------------------------------------------------------------------------
class TestLesionSegmentation:
    def test_perfect_score(self, tmp_path):
        outdir = str(tmp_path / "seg_perf")
        result_json = str(tmp_path / "result.json")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "lesion_segmentation",
            "--num-images", "5",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.0",
        ])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "lesion_segmentation",
            "--predictions", os.path.join(outdir, "pred"),
            "--ground-truth", os.path.join(outdir, "gt"),
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        for key in ["MA_AUPR", "HE_AUPR", "SE_AUPR", "EX_AUPR", "mean_AUPR"]:
            assert key in results, f"Missing key {key}"
            assert abs(results[key] - 1.0) < 1e-6, \
                f"{key} should be 1.0 for perfect predictions, got {results[key]}"

    def test_noisy_score_range(self, tmp_path):
        outdir = str(tmp_path / "seg_noisy")
        result_json = str(tmp_path / "result.json")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "lesion_segmentation",
            "--num-images", "5",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.5",
        ])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "lesion_segmentation",
            "--predictions", os.path.join(outdir, "pred"),
            "--ground-truth", os.path.join(outdir, "gt"),
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        for key in ["MA_AUPR", "HE_AUPR", "SE_AUPR", "EX_AUPR"]:
            assert 0.0 < results[key] < 1.0, \
                f"{key}={results[key]} should be in (0, 1) for noisy data"

    def test_missing_prediction_files(self, tmp_path):
        outdir = str(tmp_path / "seg_miss")
        result_json = str(tmp_path / "result.json")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "lesion_segmentation",
            "--num-images", "4",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.0",
        ])
        pred_dir = os.path.join(outdir, "pred")
        pred_files = sorted(os.listdir(pred_dir))
        if pred_files:
            os.remove(os.path.join(pred_dir, pred_files[0]))
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "lesion_segmentation",
            "--predictions", pred_dir,
            "--ground-truth", os.path.join(outdir, "gt"),
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        assert "mean_AUPR" in results

    def test_all_zero_gt(self, tmp_path):
        gt_dir = str(tmp_path / "gt")
        pred_dir = str(tmp_path / "pred")
        result_json = str(tmp_path / "result.json")
        os.makedirs(gt_dir)
        os.makedirs(pred_dir)
        for lesion in ["MA", "HE", "SE", "EX"]:
            for i in range(3):
                fname = f"img{i:03d}_{lesion}.png"
                Image.fromarray(np.zeros((64, 64), dtype=np.uint8)).save(
                    os.path.join(gt_dir, fname))
                Image.fromarray(
                    np.random.RandomState(i).randint(0, 128, (64, 64)).astype(np.uint8)
                ).save(os.path.join(pred_dir, fname))
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "lesion_segmentation",
            "--predictions", pred_dir,
            "--ground-truth", gt_dir,
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        for key in ["MA_AUPR", "HE_AUPR", "SE_AUPR", "EX_AUPR"]:
            assert results[key] == 0.0, f"{key} should be 0.0 for all-zero GT"

    def test_global_aggregation_aupr(self, tmp_path):
        """Verify global TP/FP/FN aggregation produces the correct AUPR value.
        This test uses a specific 2-image case where per-image averaging
        would give a different result than global aggregation.

        Images (2x2 each):
          img000: GT=[[255,0],[0,0]], Pred=[[255,255],[0,0]]
          img001: GT=[[255,255],[255,255]], Pred=[[255,255],[255,0]]

        With global aggregation and standard PR curve construction:
          t=0: TP=5, FP=3 -> P=0.625, R=1.0
          t>0: TP=4, FP=1 -> P=0.8, R=0.8
          Anchor (0, 1.0) + interp -> AUPR = 0.8625
        """
        gt_dir = str(tmp_path / "gt")
        pred_dir = str(tmp_path / "pred")
        result_json = str(tmp_path / "result.json")
        os.makedirs(gt_dir)
        os.makedirs(pred_dir)

        gt0 = np.array([[255, 0], [0, 0]], dtype=np.uint8)
        pred0 = np.array([[255, 255], [0, 0]], dtype=np.uint8)
        gt1 = np.array([[255, 255], [255, 255]], dtype=np.uint8)
        pred1 = np.array([[255, 255], [255, 0]], dtype=np.uint8)

        for lesion in ["MA", "HE", "SE", "EX"]:
            Image.fromarray(gt0, mode="L").save(
                os.path.join(gt_dir, f"img000_{lesion}.png"))
            Image.fromarray(pred0, mode="L").save(
                os.path.join(pred_dir, f"img000_{lesion}.png"))
            Image.fromarray(gt1, mode="L").save(
                os.path.join(gt_dir, f"img001_{lesion}.png"))
            Image.fromarray(pred1, mode="L").save(
                os.path.join(pred_dir, f"img001_{lesion}.png"))

        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "lesion_segmentation",
            "--predictions", pred_dir,
            "--ground-truth", gt_dir,
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        for key in ["MA_AUPR", "HE_AUPR", "SE_AUPR", "EX_AUPR"]:
            assert abs(results[key] - 0.8625) < 1e-4, \
                f"{key}={results[key]}, expected 0.8625"
        assert abs(results["mean_AUPR"] - 0.8625) < 1e-4

    def test_zero_pred_aupr(self, tmp_path):
        """All-zero predictions against non-zero GT should produce AUPR=0.75.
        GT: [[255,255],[0,0]] (2 positive, 2 negative)
        Pred: [[0,0],[0,0]] (all zero)

        At t=0: all positive -> P=0.5, R=1.0
        At t>0: all negative -> P=1.0 (TP+FP=0), R=0.0
        With anchor (0,1.0): AUPR = 0.75
        """
        gt_dir = str(tmp_path / "gt")
        pred_dir = str(tmp_path / "pred")
        result_json = str(tmp_path / "result.json")
        os.makedirs(gt_dir)
        os.makedirs(pred_dir)

        gt_arr = np.array([[255, 255], [0, 0]], dtype=np.uint8)
        pred_arr = np.array([[0, 0], [0, 0]], dtype=np.uint8)

        for lesion in ["MA", "HE", "SE", "EX"]:
            Image.fromarray(gt_arr, mode="L").save(
                os.path.join(gt_dir, f"img000_{lesion}.png"))
            Image.fromarray(pred_arr, mode="L").save(
                os.path.join(pred_dir, f"img000_{lesion}.png"))

        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "lesion_segmentation",
            "--predictions", pred_dir,
            "--ground-truth", gt_dir,
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        for key in ["MA_AUPR", "HE_AUPR", "SE_AUPR", "EX_AUPR"]:
            assert abs(results[key] - 0.75) < 1e-4, \
                f"{key}={results[key]}, expected 0.75"

    def test_high_noise_degrades_score(self, tmp_path):
        results_by_noise = {}
        for noise in [0.1, 0.8]:
            outdir = str(tmp_path / f"noise_{noise}")
            result_json = str(tmp_path / f"result_{noise}.json")
            run_cmd([
                "python3", GEN_SCRIPT,
                "--task", "lesion_segmentation",
                "--num-images", "8",
                "--output-dir", outdir,
                "--seed", "42",
                "--noise-level", str(noise),
            ])
            run_cmd([
                "python3", EVAL_SCRIPT,
                "--task", "lesion_segmentation",
                "--predictions", os.path.join(outdir, "pred"),
                "--ground-truth", os.path.join(outdir, "gt"),
                "--output-json", result_json,
            ])
            results_by_noise[noise] = load_json(result_json)
        assert results_by_noise[0.1]["mean_AUPR"] > results_by_noise[0.8]["mean_AUPR"], \
            "Higher noise should produce lower AUPR"


# ---------------------------------------------------------------------------
# Disease grading scoring
# ---------------------------------------------------------------------------
class TestDiseaseGrading:
    def test_perfect_score(self, tmp_path):
        outdir = str(tmp_path / "grade_perf")
        result_json = str(tmp_path / "result.json")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "disease_grading",
            "--num-images", "50",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.0",
        ])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "disease_grading",
            "--predictions", os.path.join(outdir, "pred.csv"),
            "--ground-truth", os.path.join(outdir, "gt.csv"),
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        for key in ["DR_accuracy", "DME_accuracy", "combined_accuracy"]:
            assert key in results
            assert abs(results[key] - 1.0) < 1e-6, f"{key} should be 1.0"

    def test_noisy_score(self, tmp_path):
        outdir = str(tmp_path / "grade_noisy")
        result_json = str(tmp_path / "result.json")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "disease_grading",
            "--num-images", "100",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.5",
        ])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "disease_grading",
            "--predictions", os.path.join(outdir, "pred.csv"),
            "--ground-truth", os.path.join(outdir, "gt.csv"),
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        assert results["combined_accuracy"] < 1.0
        assert results["DR_accuracy"] > 0.0
        assert results["DME_accuracy"] > 0.0

    def test_combined_accuracy_leq_individual(self, tmp_path):
        outdir = str(tmp_path / "grade_comb")
        result_json = str(tmp_path / "result.json")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "disease_grading",
            "--num-images", "100",
            "--output-dir", outdir,
            "--seed", "55",
            "--noise-level", "0.4",
        ])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "disease_grading",
            "--predictions", os.path.join(outdir, "pred.csv"),
            "--ground-truth", os.path.join(outdir, "gt.csv"),
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        assert results["combined_accuracy"] <= results["DR_accuracy"] + 1e-9
        assert results["combined_accuracy"] <= results["DME_accuracy"] + 1e-9

    def test_manual_grading(self, tmp_path):
        """Test with manually crafted CSV data where combined != average."""
        gt_csv = str(tmp_path / "gt.csv")
        pred_csv = str(tmp_path / "pred.csv")
        result_json = str(tmp_path / "result.json")
        with open(gt_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "DR_grade", "DME_grade"])
            w.writerow(["img001", 0, 0])
            w.writerow(["img002", 2, 1])
            w.writerow(["img003", 4, 2])
            w.writerow(["img004", 1, 0])
        with open(pred_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "DR_grade", "DME_grade"])
            w.writerow(["img001", 0, 0])
            w.writerow(["img002", 2, 0])
            w.writerow(["img003", 3, 2])
            w.writerow(["img004", 1, 1])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "disease_grading",
            "--predictions", pred_csv,
            "--ground-truth", gt_csv,
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        assert abs(results["DR_accuracy"] - 0.75) < 1e-6
        assert abs(results["DME_accuracy"] - 0.5) < 1e-6
        assert abs(results["combined_accuracy"] - 0.25) < 1e-6


# ---------------------------------------------------------------------------
# Localization scoring
# ---------------------------------------------------------------------------
class TestLocalization:
    def test_perfect_score(self, tmp_path):
        outdir = str(tmp_path / "loc_perf")
        result_json = str(tmp_path / "result.json")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "localization",
            "--num-images", "20",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.0",
        ])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "localization",
            "--predictions", os.path.join(outdir, "pred.csv"),
            "--ground-truth", os.path.join(outdir, "gt.csv"),
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        for key in ["OD_mean_euclidean", "fovea_mean_euclidean"]:
            assert key in results
            assert abs(results[key]) < 1e-6, \
                f"{key} should be 0.0 for perfect predictions"

    def test_noisy_score(self, tmp_path):
        outdir = str(tmp_path / "loc_noisy")
        result_json = str(tmp_path / "result.json")
        run_cmd([
            "python3", GEN_SCRIPT,
            "--task", "localization",
            "--num-images", "20",
            "--output-dir", outdir,
            "--seed", "42",
            "--noise-level", "0.5",
        ])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "localization",
            "--predictions", os.path.join(outdir, "pred.csv"),
            "--ground-truth", os.path.join(outdir, "gt.csv"),
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        assert results["OD_mean_euclidean"] > 0.0
        assert results["fovea_mean_euclidean"] > 0.0

    def test_manual_localization(self, tmp_path):
        """3-4-5 triangle: Euclidean dist for (3,4) offset = 5, not 7 (Manhattan)."""
        gt_csv = str(tmp_path / "gt.csv")
        pred_csv = str(tmp_path / "pred.csv")
        result_json = str(tmp_path / "result.json")
        with open(gt_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "OD_x", "OD_y", "fovea_x", "fovea_y"])
            w.writerow(["img001", 100.0, 200.0, 300.0, 400.0])
            w.writerow(["img002", 150.0, 250.0, 350.0, 450.0])
        with open(pred_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "OD_x", "OD_y", "fovea_x", "fovea_y"])
            w.writerow(["img001", 103.0, 204.0, 300.0, 400.0])
            w.writerow(["img002", 150.0, 250.0, 353.0, 454.0])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "localization",
            "--predictions", pred_csv,
            "--ground-truth", gt_csv,
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        assert abs(results["OD_mean_euclidean"] - 2.5) < 1e-6
        assert abs(results["fovea_mean_euclidean"] - 2.5) < 1e-6


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestErrorHandling:
    def test_unknown_image_id_grading(self, tmp_path):
        gt_csv = str(tmp_path / "gt.csv")
        pred_csv = str(tmp_path / "pred.csv")
        result_json = str(tmp_path / "result.json")
        with open(gt_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "DR_grade", "DME_grade"])
            w.writerow(["img001", 0, 0])
        with open(pred_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "DR_grade", "DME_grade"])
            w.writerow(["img001", 0, 0])
            w.writerow(["img999", 1, 1])
        rc, _, stderr = run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "disease_grading",
            "--predictions", pred_csv,
            "--ground-truth", gt_csv,
            "--output-json", result_json,
        ], expect_fail=True)
        assert rc == 1
        assert len(stderr.strip()) > 0

    def test_unknown_image_id_segmentation(self, tmp_path):
        gt_dir = str(tmp_path / "gt")
        pred_dir = str(tmp_path / "pred")
        result_json = str(tmp_path / "result.json")
        os.makedirs(gt_dir)
        os.makedirs(pred_dir)
        gt_arr = np.zeros((32, 32), dtype=np.uint8)
        gt_arr[5:15, 5:15] = 255
        Image.fromarray(gt_arr).save(os.path.join(gt_dir, "img000_MA.png"))
        Image.fromarray(gt_arr).save(os.path.join(pred_dir, "img000_MA.png"))
        Image.fromarray(gt_arr).save(os.path.join(pred_dir, "img999_MA.png"))
        rc, _, stderr = run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "lesion_segmentation",
            "--predictions", pred_dir,
            "--ground-truth", gt_dir,
            "--output-json", result_json,
        ], expect_fail=True)
        assert rc == 1

    def test_unknown_image_id_localization(self, tmp_path):
        gt_csv = str(tmp_path / "gt.csv")
        pred_csv = str(tmp_path / "pred.csv")
        result_json = str(tmp_path / "result.json")
        with open(gt_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "OD_x", "OD_y", "fovea_x", "fovea_y"])
            w.writerow(["img001", 100.0, 200.0, 300.0, 400.0])
        with open(pred_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "OD_x", "OD_y", "fovea_x", "fovea_y"])
            w.writerow(["img001", 100.0, 200.0, 300.0, 400.0])
            w.writerow(["imgXXX", 50.0, 50.0, 50.0, 50.0])
        rc, _, stderr = run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "localization",
            "--predictions", pred_csv,
            "--ground-truth", gt_csv,
            "--output-json", result_json,
        ], expect_fail=True)
        assert rc == 1

    def test_missing_gt_images_graceful(self, tmp_path):
        gt_csv = str(tmp_path / "gt.csv")
        pred_csv = str(tmp_path / "pred.csv")
        result_json = str(tmp_path / "result.json")
        with open(gt_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "OD_x", "OD_y", "fovea_x", "fovea_y"])
            w.writerow(["img001", 100.0, 200.0, 300.0, 400.0])
            w.writerow(["img002", 150.0, 250.0, 350.0, 450.0])
        with open(pred_csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["image_id", "OD_x", "OD_y", "fovea_x", "fovea_y"])
            w.writerow(["img001", 100.0, 200.0, 300.0, 400.0])
        run_cmd([
            "python3", EVAL_SCRIPT,
            "--task", "localization",
            "--predictions", pred_csv,
            "--ground-truth", gt_csv,
            "--output-json", result_json,
        ])
        results = load_json(result_json)
        assert "OD_mean_euclidean" in results


# ---------------------------------------------------------------------------
# Makefile pipeline
# ---------------------------------------------------------------------------
class TestMakefilePipeline:
    def test_make_all_produces_valid_report(self):
        """Complete pipeline: make all must produce valid report.json."""
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, timeout=30)
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0, (
            f"make all failed (exit {result.returncode})\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        report_path = "/app/output/report.json"
        assert os.path.isfile(report_path), \
            "make all did not produce /app/output/report.json"

        report = load_json(report_path)

        # Schema validation
        assert "segmentation" in report, "Missing 'segmentation' in report"
        assert "grading" in report, "Missing 'grading' in report"
        assert "localization" in report, "Missing 'localization' in report"
        assert report.get("pipeline_version") == "1.0", \
            f"pipeline_version should be '1.0', got {report.get('pipeline_version')}"

        # Segmentation values in valid range
        seg = report["segmentation"]
        for k in ["MA_AUPR", "HE_AUPR", "SE_AUPR", "EX_AUPR", "mean_AUPR"]:
            assert k in seg, f"Missing segmentation.{k}"
            assert 0.0 <= seg[k] <= 1.0, f"segmentation.{k}={seg[k]} out of [0,1]"

        # Grading values in valid range
        grade = report["grading"]
        for k in ["DR_accuracy", "DME_accuracy", "combined_accuracy"]:
            assert k in grade, f"Missing grading.{k}"
            assert 0.0 <= grade[k] <= 1.0, f"grading.{k}={grade[k]} out of [0,1]"

        # Localization values non-negative
        loc = report["localization"]
        for k in ["OD_mean_euclidean", "fovea_mean_euclidean"]:
            assert k in loc, f"Missing localization.{k}"
            assert loc[k] >= 0, f"localization.{k}={loc[k]} should be >= 0"

    def test_report_matches_individual_results(self):
        """Report contents must match individual per-task JSON files."""
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, timeout=30)
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0, f"make all failed: {result.stderr}"

        report = load_json("/app/output/report.json")
        seg = load_json("/app/output/results/seg.json")
        grade = load_json("/app/output/results/grade.json")
        loc = load_json("/app/output/results/loc.json")

        assert report["segmentation"] == seg, \
            "report.segmentation does not match seg.json"
        assert report["grading"] == grade, \
            "report.grading does not match grade.json"
        assert report["localization"] == loc, \
            "report.localization does not match loc.json"

    def test_make_clean(self):
        """make clean removes all generated output."""
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, timeout=30)
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0
        assert os.path.isdir("/app/output"), \
            "/app/output should exist after make all"
        result = subprocess.run(
            ["make", "-C", "/app", "clean"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0
        assert not os.path.isdir("/app/output"), \
            "/app/output should be removed after make clean"

    def test_pipeline_grading_combined_accuracy_correct(self):
        """Pipeline grading combined_accuracy must be <= individual accuracies."""
        subprocess.run(["make", "-C", "/app", "clean"],
                       capture_output=True, timeout=30)
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0
        report = load_json("/app/output/report.json")
        grade = report["grading"]
        assert grade["combined_accuracy"] <= grade["DR_accuracy"] + 1e-9, \
            "combined_accuracy should be <= DR_accuracy"
        assert grade["combined_accuracy"] <= grade["DME_accuracy"] + 1e-9, \
            "combined_accuracy should be <= DME_accuracy"


# ---------------------------------------------------------------------------
# End-to-end pipeline
# ---------------------------------------------------------------------------
class TestEndToEnd:
    def test_all_tasks_sequential(self, tmp_path):
        for task, keys in [
            ("lesion_segmentation",
             ["MA_AUPR", "HE_AUPR", "SE_AUPR", "EX_AUPR", "mean_AUPR"]),
            ("disease_grading",
             ["DR_accuracy", "DME_accuracy", "combined_accuracy"]),
            ("localization",
             ["OD_mean_euclidean", "fovea_mean_euclidean"]),
        ]:
            outdir = str(tmp_path / f"{task}_data")
            result_json = str(tmp_path / f"{task}_result.json")
            run_cmd([
                "python3", GEN_SCRIPT,
                "--task", task,
                "--num-images", "5",
                "--output-dir", outdir,
                "--seed", "42",
                "--noise-level", "0.2",
            ])
            if task == "lesion_segmentation":
                pred_arg = os.path.join(outdir, "pred")
                gt_arg = os.path.join(outdir, "gt")
            else:
                pred_arg = os.path.join(outdir, "pred.csv")
                gt_arg = os.path.join(outdir, "gt.csv")
            run_cmd([
                "python3", EVAL_SCRIPT,
                "--task", task,
                "--predictions", pred_arg,
                "--ground-truth", gt_arg,
                "--output-json", result_json,
            ])
            results = load_json(result_json)
            for key in keys:
                assert key in results, f"Missing key {key} in {task} results"
                assert isinstance(results[key], (int, float)), \
                    f"{key} should be numeric"

    def test_idrid_check_passes(self, tmp_path):
        """The validation harness must pass."""
        result = subprocess.run(
            ["python3", "/app/bin/idrid-check"],
            capture_output=True, text=True, timeout=300
        )
        assert result.returncode == 0, (
            f"idrid-check failed with exit code {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
