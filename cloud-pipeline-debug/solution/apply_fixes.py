#!/usr/bin/env python3

"""Apply structural fixes to the pipeline (everything except classify.py).

Fixes:
1. run_pipeline.sh - remove set -e, reorder stages, add mkdir
2. calibrate.py - correct path, fix byte order, fix formula
3. validate.py - correct shape and class set
4. score.py - correct label path, fix kappa formula

The classifier is NOT fixed here — it requires data analysis performed
by derive_classifier.py after calibration has been run.
"""
import os

# === Fix 1: run_pipeline.sh ===
with open("/app/run_pipeline.sh", "w") as f:
    f.write("""#!/bin/bash
# Fixed: removed set -e, reordered stages, added mkdir
set -uxo pipefail
exit_code=0

mkdir -p /app/output /app/calibrated /app/output/predictions

{
    cd /app

    echo "=== Land Cover Classification Pipeline ==="
    echo "$(date): Starting pipeline..."

    echo "Stage 1: Radiometric calibration..."
    python3 pipeline/calibrate.py
    if [ $? -ne 0 ]; then exit_code=1; fi

    echo "Stage 2: Land cover classification..."
    python3 pipeline/classify.py
    if [ $? -ne 0 ]; then exit_code=1; fi

    echo "Stage 3: Format validation..."
    python3 pipeline/validate.py
    if [ $? -ne 0 ]; then exit_code=1; fi

    echo "Stage 4: Computing score..."
    python3 pipeline/score.py
    if [ $? -ne 0 ]; then exit_code=1; fi

    echo "$(date): Pipeline complete"
    echo "=== END ==="
} |& tee "/app/output/pipeline.log"

exit $exit_code
""")
os.chmod("/app/run_pipeline.sh", 0o755)

# === Fix 2: calibrate.py ===
# Bugs: wrong feature path, big-endian struct unpacking, swapped gain/offset
with open("/app/pipeline/calibrate.py", "w") as f:
    f.write('''#!/usr/bin/env python3
"""Radiometric calibration: convert raw DN to TOA reflectance."""
import os
import struct
from pathlib import Path
import numpy as np
from PIL import Image

FEATURE_DIR = Path("/app/data/test_features")
CAL_DIR = Path("/app/data/calibration")
OUTPUT_DIR = Path("/app/calibrated")


def parse_cal_file(cal_path):
    coeffs = {}
    with open(cal_path, "rb") as f:
        magic = f.read(4)
        assert magic == b"SCAL"
        version = struct.unpack("<H", f.read(2))[0]
        n_bands = struct.unpack("<H", f.read(2))[0]
        for _ in range(n_bands):
            name = f.read(16).rstrip(b"\\x00").decode("ascii")
            gain = struct.unpack("<d", f.read(8))[0]
            offset = struct.unpack("<d", f.read(8))[0]
            coeffs[name] = (gain, offset)
    return coeffs


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    chips = sorted(d for d in FEATURE_DIR.iterdir() if d.is_dir())
    print("Calibrating {} chips...".format(len(chips)))

    for chip_dir in chips:
        cal_path = CAL_DIR / "{}.cal".format(chip_dir.name)
        coeffs = parse_cal_file(cal_path)
        out_dir = OUTPUT_DIR / chip_dir.name
        os.makedirs(out_dir, exist_ok=True)

        for band_name, (gain, offset) in coeffs.items():
            dn = np.array(Image.open(
                chip_dir / "{}.tif".format(band_name))).astype(np.float64)
            toa = gain * dn + offset
            np.save(str(out_dir / "{}.npy".format(band_name)), toa)

        print("  Calibrated: {}".format(chip_dir.name))

    print("Calibration complete.")


if __name__ == "__main__":
    main()
''')

# === Fix 3: validate.py ===
# Bugs: wrong expected shape (256,256) should be (512,512), missing class 3
with open("/app/pipeline/validate.py", "w") as f:
    f.write('''#!/usr/bin/env python3
"""Validate prediction outputs for format compliance."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

PREDICTION_DIR = Path("/app/output/predictions")
FEATURE_DIR = Path("/app/data/test_features")
EXPECTED_SHAPE = (512, 512)
VALID_CLASSES = {0, 1, 2, 3}
MAX_FILE_SIZE = 512 * 512 * 2


def main():
    if not PREDICTION_DIR.exists():
        print("ERROR: Prediction directory not found")
        sys.exit(1)

    chip_ids = sorted(d.name for d in FEATURE_DIR.iterdir() if d.is_dir())
    pred_ids = sorted(f.stem for f in PREDICTION_DIR.glob("*.tif"))
    errors = []

    missing = set(chip_ids) - set(pred_ids)
    if missing:
        errors.append("Missing: {}".format(sorted(missing)))

    for pred_path in sorted(PREDICTION_DIR.glob("*.tif")):
        img = np.array(Image.open(pred_path))
        if img.shape != EXPECTED_SHAPE:
            errors.append("{}: shape {}".format(pred_path.name, img.shape))
        if img.dtype != np.uint8:
            errors.append("{}: dtype {}".format(pred_path.name, img.dtype))
        invalid = set(np.unique(img)) - VALID_CLASSES
        if invalid:
            errors.append("{}: invalid {}".format(pred_path.name, invalid))

    if errors:
        print("VALIDATION FAILED:")
        for e in errors:
            print("  - {}".format(e))
        sys.exit(1)

    print("VALIDATION PASSED: {} predictions".format(len(pred_ids)))


if __name__ == "__main__":
    main()
''')

# === Fix 4: score.py ===
# Bugs: wrong label dir, kappa divides by p_e instead of (1-p_e)
with open("/app/pipeline/score.py", "w") as f:
    f.write('''#!/usr/bin/env python3
"""Compute combined classification score."""
import sys
from pathlib import Path
import numpy as np
from PIL import Image

PREDICTION_DIR = Path("/app/output/predictions")
LABEL_DIR = Path("/app/data/test_labels")
N_CLASSES = 4
CLASS_WEIGHTS = {0: 0.15, 1: 0.30, 2: 0.25, 3: 0.30}
MIN_SCORE = 0.80


def main():
    label_files = sorted(LABEL_DIR.glob("*.tif"))
    all_true, all_pred = [], []

    for lf in label_files:
        pf = PREDICTION_DIR / "{}.tif".format(lf.stem)
        if not pf.exists():
            continue
        all_true.append(np.array(Image.open(lf)).ravel())
        all_pred.append(np.array(Image.open(pf)).ravel())

    y_true = np.concatenate(all_true)
    y_pred = np.concatenate(all_pred)

    cm = np.zeros((N_CLASSES, N_CLASSES), dtype=np.int64)
    for t, p in zip(y_true, y_pred):
        if 0 <= t < N_CLASSES and 0 <= p < N_CLASSES:
            cm[int(t), int(p)] += 1

    n = cm.sum()
    p_o = float(np.diag(cm).sum()) / n
    row_sums = cm.sum(axis=1).astype(float)
    col_sums = cm.sum(axis=0).astype(float)
    p_e = float((row_sums * col_sums).sum()) / (n * n)
    kappa = (p_o - p_e) / (1.0 - p_e) if p_e < 1.0 else 0.0

    per_class_recall = np.zeros(N_CLASSES)
    for i in range(N_CLASSES):
        if row_sums[i] > 0:
            per_class_recall[i] = cm[i, i] / row_sums[i]

    weighted_recall = sum(
        CLASS_WEIGHTS[i] * per_class_recall[i] for i in range(N_CLASSES))

    score = float(np.sqrt(kappa * weighted_recall)) \\
        if kappa > 0 and weighted_recall > 0 else 0.0

    print("Confusion Matrix:")
    for row in cm:
        print("  {}".format(row))
    print("Score: {:.4f} (threshold: {:.2f})".format(score, MIN_SCORE))

    if score >= MIN_SCORE:
        print("RESULT: PASS")
    else:
        print("RESULT: FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
''')

print("All structural fixes applied successfully.")
