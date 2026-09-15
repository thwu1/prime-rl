
"""Tests for the fixed YOLO ONNX inference pipeline.

Runs /app/pipeline.py, loads its output, and compares against the
PyTorch-generated reference detections.
"""

import json
import os
import subprocess

import cv2
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _iou(box_a, box_b):
    """Compute IoU between two [x1,y1,x2,y2] boxes."""
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    return inter / (area_a + area_b - inter + 1e-8)


# ---------------------------------------------------------------------------
# session-scoped fixture: run pipeline once, share results across all tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pipeline_results():
    result = subprocess.run(
        ["python3", "/app/pipeline.py"],
        capture_output=True, text=True, cwd="/app", timeout=180,
    )
    assert result.returncode == 0, (
        f"pipeline.py exited with code {result.returncode}.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert os.path.exists("/app/detections.json"), (
        "pipeline.py did not produce /app/detections.json"
    )

    with open("/app/detections.json") as fh:
        detections = json.load(fh)
    with open("/app/reference_detections.json") as fh:
        reference = json.load(fh)

    return detections, reference


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------

def test_pipeline_runs(pipeline_results):
    """Pipeline must exit 0 and produce a non-empty JSON dict."""
    detections, _ = pipeline_results
    assert isinstance(detections, dict) and len(detections) > 0


def test_all_images_present(pipeline_results):
    """Every reference image must appear in the output."""
    detections, reference = pipeline_results
    for img in reference:
        assert img in detections, f"Missing results for {img}"


def test_no_ultralytics_import():
    """Pipeline must use onnxruntime directly, not the ultralytics library."""
    with open("/app/pipeline.py") as fh:
        src = fh.read()
    assert "ultralytics" not in src, (
        "pipeline.py must not reference ultralytics — use onnxruntime directly"
    )


def test_detection_count(pipeline_results):
    """Predicted count should be close to reference for every image."""
    detections, reference = pipeline_results
    for img in reference:
        ref_n = len(reference[img])
        pred_n = len(detections[img])
        if ref_n == 0:
            assert pred_n <= 3, (
                f"{img}: expected ~0 detections, got {pred_n}"
            )
        else:
            tol = max(3, int(ref_n * 0.35))
            assert abs(pred_n - ref_n) <= tol, (
                f"{img}: expected ~{ref_n} detections, got {pred_n}"
            )


def test_box_iou_matching(pipeline_results):
    """At least 70 % of reference detections should be matched (IoU > 0.45
    and same class_id) by some predicted detection."""
    detections, reference = pipeline_results
    matched = total = 0
    for img in reference:
        preds = detections[img]
        for ref in reference[img]:
            total += 1
            for pred in preds:
                if (
                    _iou(ref["bbox"], pred["bbox"]) > 0.45
                    and ref["class_id"] == pred["class_id"]
                ):
                    matched += 1
                    break
    ratio = matched / max(total, 1)
    assert ratio >= 0.70, (
        f"Only {ratio:.1%} of reference detections matched "
        f"(need >= 70 %). Matched {matched}/{total}."
    )


def test_class_ids_correct(pipeline_results):
    """High-confidence reference classes must appear in predictions."""
    detections, reference = pipeline_results
    for img in reference:
        ref_cls = {d["class_id"] for d in reference[img] if d["confidence"] > 0.5}
        pred_cls = {d["class_id"] for d in detections[img] if d["confidence"] > 0.3}
        if len(ref_cls) == 0:
            continue
        overlap = ref_cls & pred_cls
        assert len(overlap) >= max(1, len(ref_cls) // 2), (
            f"{img}: reference high-conf classes {ref_cls}, "
            f"predicted classes {pred_cls}"
        )


def test_confidence_range(pipeline_results):
    """Every confidence score must be in (0, 1]."""
    detections, _ = pipeline_results
    for img, dets in detections.items():
        for det in dets:
            c = det["confidence"]
            assert 0 < c <= 1.0, f"{img}: invalid confidence {c}"


def test_bbox_in_image_bounds(pipeline_results):
    """Boxes should lie approximately within the original image."""
    detections, reference = pipeline_results
    for img in reference:
        im = cv2.imread(f"/app/images/{img}")
        if im is None:
            continue
        h, w = im.shape[:2]
        for det in detections[img]:
            b = det["bbox"]
            assert b[0] >= -10 and b[1] >= -10, (
                f"{img}: box starts at negative coords {b}"
            )
            assert b[2] <= w + 10 and b[3] <= h + 10, (
                f"{img}: box exceeds image bounds {b} for {w}x{h}"
            )
            assert b[2] > b[0] and b[3] > b[1], (
                f"{img}: degenerate box {b}"
            )


def test_high_confidence_match(pipeline_results):
    """Detections with ref confidence > 0.6 must match closely (IoU > 0.6)."""
    detections, reference = pipeline_results
    matched = total = 0
    for img in reference:
        preds = detections[img]
        for ref in reference[img]:
            if ref["confidence"] <= 0.6:
                continue
            total += 1
            for pred in preds:
                if (
                    _iou(ref["bbox"], pred["bbox"]) > 0.6
                    and ref["class_id"] == pred["class_id"]
                ):
                    matched += 1
                    break
    if total > 0:
        ratio = matched / total
        assert ratio >= 0.75, (
            f"Only {ratio:.1%} of high-confidence detections matched "
            f"(need >= 75 %). Matched {matched}/{total}."
        )
