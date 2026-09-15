"""
Tests for multi-stage COCO-style mAP evaluation pipeline.
Validates that the Make-orchestrated pipeline (extraction from SQLite +
metric computation) produces results matching pycocotools reference.

"""
import json
import os
import sqlite3
import subprocess
import tempfile

import numpy as np
import yaml
from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yolo_to_coco_bbox(cx, cy, w, h, img_w, img_h):
    """Convert YOLO normalized coords to COCO absolute [x, y, w, h]."""
    aw = w * img_w
    ah = h * img_h
    x = cx * img_w - aw / 2
    y = cy * img_h - ah / 2
    return [x, y, aw, ah]


def _build_coco_data_from_files(gt_dir, pred_dir, manifest, class_names):
    """Build COCO-format GT and detection dicts from YOLO flat files."""
    images = []
    annotations = []
    detections = []
    categories = [{"id": i, "name": n} for i, n in enumerate(class_names)]
    ann_id = 1

    for img_file, dims in sorted(manifest.items()):
        img_id = int(img_file.split("_")[1].split(".")[0])
        iw, ih = dims["width"], dims["height"]
        images.append({"id": img_id, "width": iw, "height": ih,
                        "file_name": img_file})

        gt_path = os.path.join(gt_dir, img_file.replace(".png", ".txt"))
        if os.path.exists(gt_path):
            with open(gt_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) < 5:
                        continue
                    bbox = _yolo_to_coco_bbox(
                        float(parts[1]), float(parts[2]),
                        float(parts[3]), float(parts[4]), iw, ih)
                    annotations.append({
                        "id": ann_id, "image_id": img_id,
                        "category_id": int(parts[0]),
                        "bbox": bbox, "area": bbox[2] * bbox[3],
                        "iscrowd": 0
                    })
                    ann_id += 1

        pred_path = os.path.join(pred_dir, img_file.replace(".png", ".txt"))
        if os.path.exists(pred_path):
            with open(pred_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) < 6:
                        continue
                    bbox = _yolo_to_coco_bbox(
                        float(parts[1]), float(parts[2]),
                        float(parts[3]), float(parts[4]), iw, ih)
                    detections.append({
                        "image_id": img_id,
                        "category_id": int(parts[0]),
                        "bbox": bbox, "score": float(parts[5])
                    })

    gt_dict = {"images": images, "annotations": annotations,
               "categories": categories}
    return gt_dict, detections


def _compute_reference_from_db(db_path, meta_path):
    """Compute reference metrics directly from SQLite database using pycocotools.

    This reads ALL annotations from the DB (including flagged ones),
    providing the ground truth reference independent of the extraction step.
    """
    conn = sqlite3.connect(db_path)

    with open(meta_path) as f:
        meta = yaml.safe_load(f)
    class_names = [meta["names"][i] for i in range(meta["nc"])]

    categories = [{"id": i, "name": n} for i, n in enumerate(class_names)]
    images = []
    annotations = []
    detections = []

    # Load ALL images
    img_dims = {}
    for row in conn.execute(
            "SELECT image_id, filename, width, height FROM images "
            "ORDER BY image_id"):
        image_id, filename, width, height = row
        images.append({"id": image_id, "width": width, "height": height,
                        "file_name": filename})
        img_dims[image_id] = (width, height)

    # Load ALL ground truth annotations (including those with flags)
    ann_id = 1
    total_gt = 0
    for row in conn.execute(
            "SELECT image_id, class_id, cx, cy, w, h FROM ground_truth "
            "ORDER BY ann_id"):
        image_id, class_id, cx, cy, w, h = row
        iw, ih = img_dims[image_id]
        bbox = _yolo_to_coco_bbox(cx, cy, w, h, iw, ih)
        annotations.append({
            "id": ann_id, "image_id": image_id,
            "category_id": class_id,
            "bbox": bbox, "area": bbox[2] * bbox[3],
            "iscrowd": 0
        })
        ann_id += 1
        total_gt += 1

    # Load all predictions
    for row in conn.execute(
            "SELECT image_id, class_id, cx, cy, w, h, confidence "
            "FROM predictions ORDER BY det_id"):
        image_id, class_id, cx, cy, w, h, confidence = row
        iw, ih = img_dims[image_id]
        bbox = _yolo_to_coco_bbox(cx, cy, w, h, iw, ih)
        detections.append({
            "image_id": image_id,
            "category_id": class_id,
            "bbox": bbox, "score": confidence
        })

    conn.close()

    gt_dict = {"images": images, "annotations": annotations,
               "categories": categories}

    tmpdir = tempfile.mkdtemp()
    gt_path = os.path.join(tmpdir, "gt.json")
    dt_path = os.path.join(tmpdir, "dt.json")

    with open(gt_path, "w") as f:
        json.dump(gt_dict, f)

    coco_gt = COCO(gt_path)

    results = {"total_gt": total_gt, "total_images": len(images)}

    if not detections:
        results.update({
            "mAP_0.5": 0.0, "mAP_0.75": 0.0, "mAP_0.5:0.95": 0.0,
            "per_class": {n: {"ap_0.5": -1, "ap_0.75": -1,
                               "ap_0.5:0.95": -1}
                          for n in class_names},
            "per_size_small": -1.0,
            "per_size_medium": -1.0,
            "per_size_large": -1.0
        })
        return results

    with open(dt_path, "w") as f:
        json.dump(detections, f)

    coco_dt = coco_gt.loadRes(dt_path)

    ev = COCOeval(coco_gt, coco_dt, "bbox")
    ev.evaluate()
    ev.accumulate()
    ev.summarize()

    results["mAP_0.5:0.95"] = float(ev.stats[0])
    results["mAP_0.5"] = float(ev.stats[1])
    results["mAP_0.75"] = float(ev.stats[2])
    results["per_size_small"] = float(ev.stats[3])
    results["per_size_medium"] = float(ev.stats[4])
    results["per_size_large"] = float(ev.stats[5])

    per_class = {}
    for ci, cn in enumerate(class_names):
        ce = COCOeval(coco_gt, coco_dt, "bbox")
        ce.params.catIds = [ci]
        ce.evaluate()
        ce.accumulate()
        ce.summarize()
        per_class[cn] = {
            "ap_0.5": float(ce.stats[1]),
            "ap_0.75": float(ce.stats[2]),
            "ap_0.5:0.95": float(ce.stats[0]),
        }
    results["per_class"] = per_class
    return results


# ---------------------------------------------------------------------------
# Main test suite -- full pipeline on synthetic 80-image dataset
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """Validate full make pipeline output against pycocotools reference."""

    @classmethod
    def setup_class(cls):
        assert os.path.exists("/app/data/annotations.db"), \
            "Database missing -- did generate_dataset.py run?"
        assert os.path.exists("/app/results.json"), \
            "results.json not created -- did 'make evaluate' succeed?"

        with open("/app/results.json") as f:
            cls.results = json.load(f)

        cls.ref = _compute_reference_from_db(
            "/app/data/annotations.db",
            "/app/data/meta.yaml"
        )

    # -- schema tests -------------------------------------------------------

    def test_has_map_key(self):
        assert "mAP" in self.results

    def test_map_subkeys(self):
        for k in ("0.5", "0.75", "0.5:0.95"):
            assert k in self.results["mAP"], f"Missing mAP key: {k}"

    def test_has_per_class(self):
        assert "per_class" in self.results

    def test_has_per_size(self):
        assert "per_size" in self.results

    def test_all_classes_present(self):
        expected = ["boneanomaly", "bonelesion", "foreignbody", "fracture",
                     "metal", "periostealreaction", "pronatorsign",
                     "softtissue", "text"]
        for c in expected:
            assert c in self.results["per_class"], f"Missing class: {c}"

    def test_per_size_categories(self):
        for s in ("small", "medium", "large"):
            assert s in self.results["per_size"], f"Missing size: {s}"
            assert "ap_0.5:0.95" in self.results["per_size"][s]
            assert "n_gt" in self.results["per_size"][s]

    def test_per_class_schema(self):
        for cn, data in self.results["per_class"].items():
            for k in ("ap_0.5", "ap_0.75", "ap_0.5:0.95", "n_gt", "n_det",
                       "optimal_f1"):
                assert k in data, f"Missing {k} for class {cn}"
            f1d = data["optimal_f1"]
            for k in ("threshold", "f1", "precision", "recall"):
                assert k in f1d, f"Missing optimal_f1.{k} for class {cn}"

    # -- value range tests --------------------------------------------------

    def test_map_values_in_range(self):
        for k in ("0.5", "0.75", "0.5:0.95"):
            v = float(self.results["mAP"][k])
            assert 0.0 <= v <= 1.0, f"mAP@{k} = {v} out of [0,1]"

    def test_map_ordering(self):
        m50 = float(self.results["mAP"]["0.5"])
        m75 = float(self.results["mAP"]["0.75"])
        m5095 = float(self.results["mAP"]["0.5:0.95"])
        assert m50 >= m75 - 0.01, f"mAP@0.5({m50}) < mAP@0.75({m75})"
        assert m50 >= m5095 - 0.01, \
            f"mAP@0.5({m50}) < mAP@0.5:0.95({m5095})"

    def test_per_size_values_in_range(self):
        for s in ("small", "medium", "large"):
            v = float(self.results["per_size"][s]["ap_0.5:0.95"])
            assert 0.0 <= v <= 1.0, f"{s} AP = {v} out of [0,1]"

    def test_optimal_f1_values_in_range(self):
        for cn, data in self.results["per_class"].items():
            f1d = data["optimal_f1"]
            assert 0.0 <= float(f1d["f1"]) <= 1.0
            assert 0.0 <= float(f1d["threshold"]) <= 1.0
            assert 0.0 <= float(f1d["precision"]) <= 1.0
            assert 0.0 <= float(f1d["recall"]) <= 1.0

    # -- accuracy tests vs pycocotools reference ----------------------------

    def test_map_50(self):
        res = float(self.results["mAP"]["0.5"])
        ref = self.ref["mAP_0.5"]
        assert abs(res - ref) < 0.02, f"mAP@0.5: {res} vs ref {ref}"

    def test_map_75(self):
        res = float(self.results["mAP"]["0.75"])
        ref = self.ref["mAP_0.75"]
        assert abs(res - ref) < 0.02, f"mAP@0.75: {res} vs ref {ref}"

    def test_map_50_95(self):
        res = float(self.results["mAP"]["0.5:0.95"])
        ref = self.ref["mAP_0.5:0.95"]
        assert abs(res - ref) < 0.02, f"mAP@0.5:0.95: {res} vs ref {ref}"

    def test_per_class_ap_50(self):
        tol = 0.03
        for cn, rv in self.ref["per_class"].items():
            if rv["ap_0.5"] < 0:
                continue
            res = float(self.results["per_class"][cn]["ap_0.5"])
            ref = rv["ap_0.5"]
            assert abs(res - ref) < tol, f"{cn} AP@0.5: {res} vs {ref}"

    def test_per_class_ap_75(self):
        tol = 0.03
        for cn, rv in self.ref["per_class"].items():
            if rv["ap_0.75"] < 0:
                continue
            res = float(self.results["per_class"][cn]["ap_0.75"])
            ref = rv["ap_0.75"]
            assert abs(res - ref) < tol, f"{cn} AP@0.75: {res} vs {ref}"

    def test_per_class_ap_50_95(self):
        tol = 0.03
        for cn, rv in self.ref["per_class"].items():
            if rv["ap_0.5:0.95"] < 0:
                continue
            res = float(self.results["per_class"][cn]["ap_0.5:0.95"])
            ref = rv["ap_0.5:0.95"]
            assert abs(res - ref) < tol, f"{cn} AP@0.5:0.95: {res} vs {ref}"

    def test_n_gt_positive(self):
        total = sum(d["n_gt"] for d in self.results["per_class"].values())
        assert total > 0, "Total n_gt should be positive"

    # -- extraction validation (catches SQL bugs) ---------------------------

    def test_total_gt_matches_database(self):
        """Total n_gt across classes must equal actual GT rows in database."""
        total_reported = sum(
            d["n_gt"] for d in self.results["per_class"].values())
        assert total_reported == self.ref["total_gt"], \
            f"Total n_gt {total_reported} != DB GT count {self.ref['total_gt']}"

    def test_manifest_covers_all_images(self):
        """Manifest must include every image in the database."""
        with open("/app/data/manifest.json") as f:
            manifest = json.load(f)
        assert len(manifest) == self.ref["total_images"], \
            f"Manifest has {len(manifest)} images, DB has {self.ref['total_images']}"

    def test_extraction_covers_all_images(self):
        """GT and prediction directories must have files for every DB image."""
        gt_files = set(f for f in os.listdir("/app/data/ground_truth")
                       if f.endswith(".txt"))
        pred_files = set(f for f in os.listdir("/app/data/predictions")
                         if f.endswith(".txt"))
        assert len(gt_files) == self.ref["total_images"], \
            f"GT files: {len(gt_files)} != DB images: {self.ref['total_images']}"
        assert len(pred_files) == self.ref["total_images"], \
            f"Pred files: {len(pred_files)} != DB images: {self.ref['total_images']}"

    # -- per-size reference tests -------------------------------------------

    def test_per_size_small_ap(self):
        ref = self.ref["per_size_small"]
        if ref < 0:
            return
        res = float(self.results["per_size"]["small"]["ap_0.5:0.95"])
        assert abs(res - ref) < 0.05, f"small AP: {res} vs ref {ref}"

    def test_per_size_medium_ap(self):
        ref = self.ref["per_size_medium"]
        if ref < 0:
            return
        res = float(self.results["per_size"]["medium"]["ap_0.5:0.95"])
        assert abs(res - ref) < 0.05, f"medium AP: {res} vs ref {ref}"

    def test_per_size_large_ap(self):
        ref = self.ref["per_size_large"]
        if ref < 0:
            return
        res = float(self.results["per_size"]["large"]["ap_0.5:0.95"])
        assert abs(res - ref) < 0.05, f"large AP: {res} vs ref {ref}"

    # -- anti-cheat ----------------------------------------------------------

    def test_no_pycocotools_in_evaluator(self):
        with open("/app/evaluate.py") as f:
            code = f.read()
        assert "pycocotools" not in code, \
            "evaluate.py must not import or reference pycocotools"

    def test_no_cocoeval_in_evaluator(self):
        with open("/app/evaluate.py") as f:
            code = f.read().lower()
        assert "cocoeval" not in code, \
            "evaluate.py must not use COCOeval"


# ---------------------------------------------------------------------------
# Edge-case test suite -- hand-crafted minimal dataset
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Validate evaluator on known edge-case scenarios."""

    @classmethod
    def setup_class(cls):
        edge_dir = "/app/data_edge"
        gt_dir = os.path.join(edge_dir, "ground_truth")
        pred_dir = os.path.join(edge_dir, "predictions")
        os.makedirs(gt_dir, exist_ok=True)
        os.makedirs(pred_dir, exist_ok=True)

        manifest = {}

        # Image 0: perfect detection
        manifest["image_0000.png"] = {"width": 1000, "height": 1000}
        with open(os.path.join(gt_dir, "image_0000.txt"), "w") as f:
            f.write("3 0.5 0.5 0.2 0.2\n")
        with open(os.path.join(pred_dir, "image_0000.txt"), "w") as f:
            f.write("3 0.5 0.5 0.2 0.2 0.95\n")

        # Image 1: missed detection (GT with no prediction)
        manifest["image_0001.png"] = {"width": 1000, "height": 1000}
        with open(os.path.join(gt_dir, "image_0001.txt"), "w") as f:
            f.write("3 0.3 0.3 0.1 0.1\n")
        with open(os.path.join(pred_dir, "image_0001.txt"), "w") as f:
            f.write("")

        # Image 2: false positive (prediction with no GT)
        manifest["image_0002.png"] = {"width": 1000, "height": 1000}
        with open(os.path.join(gt_dir, "image_0002.txt"), "w") as f:
            f.write("")
        with open(os.path.join(pred_dir, "image_0002.txt"), "w") as f:
            f.write("3 0.7 0.7 0.15 0.15 0.80\n")

        # Image 3: 2 GT, 3 predictions (1 TP, 1 duplicate near-match FP, 1 TP)
        manifest["image_0003.png"] = {"width": 1000, "height": 1000}
        with open(os.path.join(gt_dir, "image_0003.txt"), "w") as f:
            f.write("3 0.3 0.3 0.1 0.1\n3 0.7 0.7 0.1 0.1\n")
        with open(os.path.join(pred_dir, "image_0003.txt"), "w") as f:
            f.write("3 0.3 0.3 0.1 0.1 0.90\n"
                    "3 0.31 0.31 0.1 0.1 0.85\n"
                    "3 0.7 0.7 0.1 0.1 0.70\n")

        # Image 4: GT with extra field (difficulty flag) -- must still be parsed
        manifest["image_0004.png"] = {"width": 800, "height": 600}
        with open(os.path.join(gt_dir, "image_0004.txt"), "w") as f:
            f.write("3 0.5 0.5 0.15 0.15 1\n")
        with open(os.path.join(pred_dir, "image_0004.txt"), "w") as f:
            f.write("3 0.5 0.5 0.15 0.15 0.88\n")

        with open(os.path.join(edge_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

        result = subprocess.run(
            ["python3", "/app/evaluate.py",
             "--ground-truth", gt_dir,
             "--predictions", pred_dir,
             "--manifest", os.path.join(edge_dir, "manifest.json"),
             "--config", "/app/data/meta.yaml",
             "--output", "/app/results_edge.json"],
            capture_output=True, text=True, timeout=60
        )
        assert result.returncode == 0, \
            f"Edge case eval failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"

        with open("/app/results_edge.json") as f:
            cls.results = json.load(f)

        # Reference for edge dataset
        with open("/app/data/meta.yaml") as f:
            meta = yaml.safe_load(f)
        class_names = [meta["names"][i] for i in range(meta["nc"])]
        gt_dict, dets = _build_coco_data_from_files(
            gt_dir, pred_dir, manifest, class_names)
        tmpdir = tempfile.mkdtemp()
        gp = os.path.join(tmpdir, "gt_e.json")
        dp = os.path.join(tmpdir, "dt_e.json")
        with open(gp, "w") as f:
            json.dump(gt_dict, f)
        with open(dp, "w") as f:
            json.dump(dets, f)
        coco_gt = COCO(gp)
        coco_dt = coco_gt.loadRes(dp)
        ce = COCOeval(coco_gt, coco_dt, "bbox")
        ce.params.catIds = [3]
        ce.evaluate()
        ce.accumulate()
        ce.summarize()
        cls.ref_fracture_ap50 = float(ce.stats[1])

    def test_fracture_ap_edge(self):
        res = float(self.results["per_class"]["fracture"]["ap_0.5"])
        assert abs(res - self.ref_fracture_ap50) < 0.03, \
            f"Edge fracture AP@0.5: {res} vs ref {self.ref_fracture_ap50}"

    def test_fracture_n_gt_with_extra_field(self):
        """GT count must include annotations with extra fields (5 total)."""
        assert self.results["per_class"]["fracture"]["n_gt"] == 5

    def test_classes_without_gt_have_zero(self):
        for cn in ("boneanomaly", "bonelesion", "foreignbody", "metal",
                    "periostealreaction", "pronatorsign", "softtissue",
                    "text"):
            assert self.results["per_class"][cn]["n_gt"] == 0, \
                f"{cn} should have 0 GT in edge dataset"

    def test_edge_map_nonzero(self):
        """Only fracture has GT, so mAP should reflect fracture AP."""
        m = float(self.results["mAP"]["0.5"])
        assert m > 0.0, "mAP@0.5 should be > 0 on edge dataset"

    def test_edge_map_excludes_zero_gt_classes(self):
        """mAP must equal fracture AP (only class with GT)."""
        m50 = float(self.results["mAP"]["0.5"])
        frac_ap = float(self.results["per_class"]["fracture"]["ap_0.5"])
        assert abs(m50 - frac_ap) < 0.001, \
            f"mAP@0.5 ({m50}) should equal fracture AP ({frac_ap})"

    def test_edge_output_valid_json(self):
        """Verify output is valid and parseable."""
        for k in ("mAP", "per_class", "per_size"):
            assert k in self.results, f"Missing key: {k}"
