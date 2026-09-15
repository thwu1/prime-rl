
"""Verification tests for the land cover classification pipeline."""
import os
from pathlib import Path

import numpy as np
from PIL import Image


PRED_DIR = Path("/app/output/predictions")
FEATURE_DIR = Path("/app/data/test_features")
LABEL_DIR = Path("/app/data/test_labels")
LOG_PATH = Path("/app/output/pipeline.log")

EXPECTED_SHAPE = (512, 512)
VALID_CLASSES = {0, 1, 2, 3}
N_CLASSES = 4
CLASS_WEIGHTS = {0: 0.15, 1: 0.30, 2: 0.25, 3: 0.30}
MIN_SCORE = 0.80


def _chip_ids():
    return sorted(d.name for d in FEATURE_DIR.iterdir() if d.is_dir())


def test_prediction_directory_exists():
    assert PRED_DIR.exists(), \
        "Prediction directory {} does not exist".format(PRED_DIR)


def test_all_predictions_present():
    chip_ids = _chip_ids()
    pred_ids = sorted(f.stem for f in PRED_DIR.glob("*.tif"))
    missing = set(chip_ids) - set(pred_ids)
    assert len(missing) == 0, \
        "Missing predictions: {}".format(sorted(missing))


def test_no_extra_predictions():
    chip_ids = set(_chip_ids())
    pred_ids = set(f.stem for f in PRED_DIR.glob("*.tif"))
    extra = pred_ids - chip_ids
    assert len(extra) == 0, \
        "Extra predictions: {}".format(sorted(extra))


def test_prediction_shapes():
    for pf in sorted(PRED_DIR.glob("*.tif")):
        img = np.array(Image.open(pf))
        assert img.shape == EXPECTED_SHAPE, \
            "{}: shape {} != {}".format(pf.name, img.shape, EXPECTED_SHAPE)


def test_prediction_dtype():
    for pf in sorted(PRED_DIR.glob("*.tif")):
        img = np.array(Image.open(pf))
        assert img.dtype == np.uint8, \
            "{}: dtype {} != uint8".format(pf.name, img.dtype)


def test_prediction_values():
    for pf in sorted(PRED_DIR.glob("*.tif")):
        img = np.array(Image.open(pf))
        vals = set(np.unique(img))
        assert vals.issubset(VALID_CLASSES), \
            "{}: invalid classes {}".format(pf.name, vals - VALID_CLASSES)


def test_all_classes_represented():
    all_vals = set()
    for pf in sorted(PRED_DIR.glob("*.tif")):
        all_vals.update(np.unique(np.array(Image.open(pf))))
    assert all_vals == VALID_CLASSES, \
        "Not all 4 classes present across predictions: found {}".format(
            all_vals)


def test_combined_score_meets_threshold():
    """Geometric mean of Cohen's kappa and weighted recall >= 0.80."""
    all_true = []
    all_pred = []

    for lf in sorted(LABEL_DIR.glob("*.tif")):
        pf = PRED_DIR / "{}.tif".format(lf.stem)
        assert pf.exists(), "Missing prediction for {}".format(lf.stem)
        all_true.append(np.array(Image.open(lf)).ravel())
        all_pred.append(np.array(Image.open(pf)).ravel())

    y_true = np.concatenate(all_true)
    y_pred = np.concatenate(all_pred)

    cm = np.zeros((N_CLASSES, N_CLASSES), dtype=np.int64)
    for t, p in zip(y_true, y_pred):
        if 0 <= t < N_CLASSES and 0 <= p < N_CLASSES:
            cm[int(t), int(p)] += 1

    n = cm.sum()
    assert n > 0, "Empty confusion matrix"

    p_o = float(np.diag(cm).sum()) / n
    row_sums = cm.sum(axis=1).astype(float)
    col_sums = cm.sum(axis=0).astype(float)
    p_e = float((row_sums * col_sums).sum()) / (n * n)
    kappa = (p_o - p_e) / (1.0 - p_e) if p_e < 1.0 else 0.0

    per_class_recall = np.zeros(N_CLASSES)
    for i in range(N_CLASSES):
        if row_sums[i] > 0:
            per_class_recall[i] = float(cm[i, i]) / row_sums[i]

    weighted_recall = sum(
        CLASS_WEIGHTS.get(i, 0.0) * per_class_recall[i]
        for i in range(N_CLASSES)
    )

    if kappa > 0 and weighted_recall > 0:
        score = float(np.sqrt(kappa * weighted_recall))
    else:
        score = 0.0

    assert score >= MIN_SCORE, \
        "Score {:.4f} < threshold {:.2f}".format(score, MIN_SCORE)


def test_pipeline_log_exists():
    assert LOG_PATH.exists(), \
        "Pipeline log not found at {}".format(LOG_PATH)
    content = LOG_PATH.read_text()
    assert len(content) > 0, "Pipeline log is empty"
