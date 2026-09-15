#!/usr/bin/env python3
"""Fix all pipeline bugs and create adaptive multi-index cloud detector.

Fixes:
1. metric.py: IoU/Dice empty-mask handling, Dice coefficient factor, composite weights
2. test_submission.py: glob pattern on directories, missing numpy import
3. Makefile: python interpreter, validation path, detect dependency, mkdir
4. Creates adaptive detector at /app/detector/main.py
"""

import os

###############################################################################
# Fix 1: scoring/metric.py — 4 bugs
#   - IoU returns 0.0 for both-empty masks → should return 1.0
#   - Dice returns 0.0 for both-empty masks → should return 1.0
#   - Dice uses 3*intersection instead of 2*intersection
#   - Composite weights sum to 1.1 (0.5+0.6) instead of 1.0
###############################################################################

METRIC_PY = '''\
#!/usr/bin/env python3
"""Multi-metric scoring for cloud mask predictions."""
import numpy as np
from PIL import Image
from pathlib import Path
import json
import sys


def compute_iou(pred, gt):
    pred_bin = (pred > 0).astype(np.uint8)
    gt_bin = (gt > 0).astype(np.uint8)
    intersection = np.sum(np.logical_and(pred_bin, gt_bin))
    union = np.sum(np.logical_or(pred_bin, gt_bin))
    if union == 0:
        return 1.0
    return float(intersection) / float(union)


def compute_dice(pred, gt):
    pred_bin = (pred > 0).astype(np.uint8)
    gt_bin = (gt > 0).astype(np.uint8)
    intersection = np.sum(np.logical_and(pred_bin, gt_bin))
    pred_sum = np.sum(pred_bin)
    gt_sum = np.sum(gt_bin)
    if pred_sum + gt_sum == 0:
        return 1.0
    return float(2 * intersection) / float(pred_sum + gt_sum)


def composite_score(iou, dice):
    return 0.5 * iou + 0.5 * dice


def main(predictions_dir, labels_dir, output_path):
    pred_dir = Path(predictions_dir)
    label_dir = Path(labels_dir)
    pred_files = sorted(pred_dir.glob("*.tif"))
    if not pred_files:
        print("ERROR: No prediction files found")
        sys.exit(1)

    per_chip = {}
    for pred_file in pred_files:
        chip_id = pred_file.stem
        label_file = label_dir / f"{chip_id}.tif"
        if not label_file.exists():
            continue
        pred = np.array(Image.open(pred_file))
        gt = np.array(Image.open(label_file))
        iou = compute_iou(pred, gt)
        dice = compute_dice(pred, gt)
        comp = composite_score(iou, dice)
        per_chip[chip_id] = {\'iou\': iou, \'dice\': dice, \'composite\': comp}

    ious = [v[\'iou\'] for v in per_chip.values()]
    dices = [v[\'dice\'] for v in per_chip.values()]
    overall_iou = float(np.mean(ious))
    overall_dice = float(np.mean(dices))

    result = {
        \'overall_iou\': overall_iou,
        \'overall_dice\': overall_dice,
        \'composite_score\': composite_score(overall_iou, overall_dice),
        \'num_chips\': len(per_chip),
        \'per_chip\': per_chip,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, \'w\') as f:
        json.dump(result, f, indent=2)
    print(f"Overall IoU: {overall_iou:.4f}, Dice: {overall_dice:.4f}")


if __name__ == \'__main__\':
    if len(sys.argv) != 4:
        print("Usage: metric.py <predictions_dir> <labels_dir> <output_json>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
'''

with open('/app/scoring/metric.py', 'w') as f:
    f.write(METRIC_PY)


###############################################################################
# Fix 2: validation/test_submission.py — 2 bugs
#   - glob("*.tif") on directory of subdirectories returns empty set
#   - numpy not imported but used in test functions
###############################################################################

VALIDATION_PY = '''\
"""Validate cloud mask predictions format."""
from pathlib import Path
from PIL import Image
import numpy as np

SUBMISSION_DIR = Path("/app/predictions")
TEST_DIR = Path("/app/data/test_features")
MAX_FILE_SIZE = 512 * 512 * 2
EXPECTED_SHAPE = (512, 512)
EXPECTED_VALUES = {0, 1}

image_names = set(
    d.name for d in TEST_DIR.iterdir() if d.is_dir()
)
submission_names = set(path.stem for path in SUBMISSION_DIR.glob("*.tif"))


def test_no_missing_files():
    missing = image_names - submission_names
    assert len(missing) == 0, f"Missing predictions: {missing}"


def test_no_extra_files():
    extra = submission_names - image_names
    assert len(extra) == 0, f"Extra predictions: {extra}"


def test_valid_dimensions():
    for name in submission_names:
        img = np.array(Image.open(SUBMISSION_DIR / f"{name}.tif"))
        assert img.shape == EXPECTED_SHAPE, f"{name} shape={img.shape}"


def test_valid_values():
    for name in submission_names:
        img = np.array(Image.open(SUBMISSION_DIR / f"{name}.tif"))
        extra = set(np.unique(img)) - EXPECTED_VALUES
        assert len(extra) == 0, f"Invalid values {extra} in {name}"


def test_file_sizes():
    for name in submission_names:
        size = (SUBMISSION_DIR / f"{name}.tif").stat().st_size
        assert size <= MAX_FILE_SIZE, f"{name} too large: {size}"
'''

with open('/app/validation/test_submission.py', 'w') as f:
    f.write(VALIDATION_PY)


###############################################################################
# Fix 3: Makefile — 4 bugs
#   - PYTHON = python → python3
#   - validate path: tests/test_submission.py → validation/test_submission.py
#   - score target missing detect dependency
#   - score recipe missing mkdir -p for results directory
# Also update DETECTOR_DIR to point to the new adaptive detector
###############################################################################

MAKEFILE = (
    "PYTHON = python3\n"
    "DETECTOR_DIR = detector\n"
    "PREDICTIONS_DIR = predictions\n"
    "RESULTS_DIR = results\n"
    "DATA_DIR = data\n"
    "\n"
    ".PHONY: detect validate score clean\n"
    "\n"
    "detect:\n"
    "\t$(PYTHON) $(DETECTOR_DIR)/main.py\n"
    "\n"
    "validate:\n"
    "\t$(PYTHON) -m pytest validation/test_submission.py -v\n"
    "\n"
    "score: detect validate\n"
    "\tmkdir -p $(RESULTS_DIR)\n"
    "\t$(PYTHON) scoring/metric.py $(PREDICTIONS_DIR) $(DATA_DIR)/test_labels $(RESULTS_DIR)/score.json\n"
    "\n"
    "clean:\n"
    "\trm -rf $(PREDICTIONS_DIR) $(RESULTS_DIR)\n"
)

with open('/app/Makefile', 'w') as f:
    f.write(MAKEFILE)


###############################################################################
# Create adaptive multi-index cloud detector
#
# Strategy:
#   1. Compute spectral indices (NDVI, brightness) per chip
#   2. Classify terrain from median spectral statistics:
#      - High median NDVI (> 0.3) → vegetation
#      - High median NDWI (> 0.2) → water
#      - Otherwise → urban/bare-soil
#   3. Apply terrain-specific cloud detection:
#      - Vegetation: NDVI < 0.2 → cloud (clouds have low NDVI)
#      - Water: brightness > 4000 → cloud (clear water is very dark, clouds bright)
#      - Urban: brightness > 5000 → cloud (clear urban moderate, clouds bright)
###############################################################################

os.makedirs('/app/detector', exist_ok=True)

DETECTOR_PY = '''\
#!/usr/bin/env python3
"""Adaptive multi-index cloud detection.

Classifies terrain type per chip from spectral statistics, then applies
the optimal spectral index and threshold for that terrain.
"""
from pathlib import Path
import numpy as np
from PIL import Image

DATA_DIR = Path("/app/data/test_features")
PREDICTIONS_DIR = Path("/app/predictions")


def read_bands(chip_dir):
    bands = {}
    for name in [\'B02\', \'B03\', \'B04\', \'B08\']:
        bands[name] = np.array(Image.open(chip_dir / f"{name}.tif")).astype(np.float32)
    return bands


def compute_ndvi(bands):
    denom = bands[\'B08\'] + bands[\'B04\']
    denom[denom == 0] = 1
    return (bands[\'B08\'] - bands[\'B04\']) / denom


def compute_ndwi(bands):
    denom = bands[\'B03\'] + bands[\'B08\']
    denom[denom == 0] = 1
    return (bands[\'B03\'] - bands[\'B08\']) / denom


def compute_brightness(bands):
    return (bands[\'B02\'] + bands[\'B03\'] + bands[\'B04\'] + bands[\'B08\']) / 4.0


def classify_terrain(bands):
    ndvi = compute_ndvi(bands)
    ndwi = compute_ndwi(bands)
    if np.median(ndvi) > 0.3:
        return \'vegetation\'
    elif np.median(ndwi) > 0.2:
        return \'water\'
    else:
        return \'urban\'


def detect_clouds(bands, terrain):
    if terrain == \'vegetation\':
        ndvi = compute_ndvi(bands)
        return (ndvi < 0.2).astype(np.uint8)
    elif terrain == \'water\':
        brightness = compute_brightness(bands)
        return (brightness > 4000).astype(np.uint8)
    else:
        brightness = compute_brightness(bands)
        return (brightness > 5000).astype(np.uint8)


def main():
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    chips = sorted(d for d in DATA_DIR.iterdir() if d.is_dir())
    for chip_dir in chips:
        bands = read_bands(chip_dir)
        terrain = classify_terrain(bands)
        mask = detect_clouds(bands, terrain)
        Image.fromarray(mask).save(PREDICTIONS_DIR / f"{chip_dir.name}.tif")
        print(f"{chip_dir.name}: terrain={terrain}, cloud={np.mean(mask)*100:.1f}%")


if __name__ == "__main__":
    main()
'''

with open('/app/detector/main.py', 'w') as f:
    f.write(DETECTOR_PY)

print("All fixes applied and adaptive detector created.")
