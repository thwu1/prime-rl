A satellite imagery cloud detection evaluation pipeline is at `/app/`. Pre-generated synthetic Sentinel-2 multi-band data covers 12 chips spanning vegetation, water, and urban/bare-soil terrain at `/app/data/test_features/`. Ground truth cloud masks are at `/app/data/test_labels/`. Terrain labels are not provided; terrain type must be inferred from the spectral characteristics of the imagery itself.

A baseline NDVI-only detector is at `/app/baseline/main.py`. It uses a single spectral index with a fixed global threshold. It achieves acceptable accuracy on vegetation terrain but performs poorly on water and urban terrain because those surface types have spectral signatures that cause NDVI-based detection to systematically misclassify clear surface pixels as cloud. A single-index approach with a fixed threshold is insufficient to handle all terrain types.

The multi-metric scoring module (`/app/scoring/metric.py`) computes IoU, Dice coefficient, and a weighted composite score but contains bugs in its metric implementations and edge-case handling. The validation test suite (`/app/validation/test_submission.py`) and the Makefile (`/app/Makefile`) also contain bugs that prevent the pipeline from executing correctly.

Design and implement a cloud detection solution that achieves high accuracy across all terrain types. Fix all infrastructure bugs so that running `make score` from `/app/` produces `/app/results/score.json` satisfying:

- `overall_iou` > 0.85
- `overall_dice` > 0.85
- `composite_score` in the range (0.0, 1.0]
- `num_chips` = 12
- Every chip's `iou` within `per_chip` > 0.70

Each band image is 512x512 pixels (uint16, range 0-10000 reflectance units). Available bands per chip: B02 (Blue), B03 (Green), B04 (Red), B08 (NIR).