from pathlib import Path

from PIL import Image
import numpy as np

SUBMISSION_DIR = Path("/app/predictions")
TEST_DIR = Path("/app/data/test_features")
MAX_FILE_SIZE = 512 * 512 * 2  # 2x fudge factor
EXPECTED_SHAPE = (512, 512)
EXPECTED_VALUES = {0, 1}

image_names = set(
    path.stem for path in TEST_DIR.glob("*") if path.is_dir()
)
submission_names = set(path.stem for path in SUBMISSION_DIR.glob("*.tif"))


def test_no_missing_files():
    missing = image_names - submission_names
    assert len(missing) == 0, (
        "Missing predictions for: {}".format(", ".join(sorted(missing)))
    )


def test_no_extra_files():
    extra = submission_names - image_names
    assert len(extra) == 0, (
        "Extra prediction files: {}".format(", ".join(sorted(extra)))
    )


def test_valid_shapes():
    for name in submission_names:
        img = np.array(Image.open(SUBMISSION_DIR / "{}.tif".format(name)))
        assert img.shape == EXPECTED_SHAPE, (
            "{} shape={}, expected {}".format(name, img.shape, EXPECTED_SHAPE)
        )


def test_valid_values():
    for name in submission_names:
        img = np.array(Image.open(SUBMISSION_DIR / "{}.tif".format(name)))
        extra_vals = set(np.unique(img)) - EXPECTED_VALUES
        assert len(extra_vals) == 0, (
            "Invalid values {} in {}.tif".format(extra_vals, name)
        )


def test_file_sizes():
    for name in submission_names:
        size = (SUBMISSION_DIR / "{}.tif".format(name)).stat().st_size
        assert size <= MAX_FILE_SIZE, (
            "{} is {:,} bytes, limit is {:,}".format(name, size, MAX_FILE_SIZE)
        )
