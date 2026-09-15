"""Validate that cloud mask predictions conform to the required format.

Checks:
- All chips have corresponding predictions
- No extra prediction files
- Correct shape (512x512)
- Correct values ({0, 1} binary)
- File size within limits
"""

from pathlib import Path
from PIL import Image

SUBMISSION_DIR = Path("/app/predictions")
TEST_DIR = Path("/app/data/test_features")
MAX_FILE_SIZE = 512 * 512 * 2
EXPECTED_SHAPE = (512, 512)
EXPECTED_VALUES = {0, 1}

# Discover chip IDs from the test features directory
image_names = set(
    path.stem for path in TEST_DIR.glob("*.tif")
)
submission_names = set(path.stem for path in SUBMISSION_DIR.glob("*.tif"))


def test_no_missing_files():
    """Every test chip must have a corresponding prediction."""
    missing = image_names - submission_names
    assert len(missing) == 0, f"Missing predictions: {missing}"


def test_no_extra_files():
    """Submission must not include predictions for non-existent chips."""
    extra = submission_names - image_names
    assert len(extra) == 0, f"Extra predictions: {extra}"


def test_valid_dimensions():
    """Each prediction must be 512x512."""
    for name in submission_names:
        img = np.array(Image.open(SUBMISSION_DIR / f"{name}.tif"))
        assert img.shape == EXPECTED_SHAPE, \
            f"{name} shape={img.shape}, expected {EXPECTED_SHAPE}"


def test_valid_values():
    """Each prediction must contain only values 0 and 1."""
    for name in submission_names:
        img = np.array(Image.open(SUBMISSION_DIR / f"{name}.tif"))
        extra = set(np.unique(img)) - EXPECTED_VALUES
        assert len(extra) == 0, f"Invalid values {extra} in {name}"


def test_file_sizes():
    """Prediction files must not exceed the size limit."""
    for name in submission_names:
        size = (SUBMISSION_DIR / f"{name}.tif").stat().st_size
        assert size <= MAX_FILE_SIZE, f"{name} too large: {size}"
