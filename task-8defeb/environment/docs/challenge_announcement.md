# ISLES-26: Ischemic Stroke Lesion Segmentation Challenge

## Challenge Overview

Teams submit Docker containers that produce binary infarct lesion masks from native-space T1w brain MRIs collected across 60+ imaging centers worldwide. Predictions are evaluated against expert-annotated ground truth using metrics that jointly assess voxel-level segmentation accuracy and clinically meaningful lesion-level detection performance.

## Data Format

All images use NIfTI-1 format (`.nii.gz`). Spatial resolution varies substantially across acquisition centers (voxel sizes ranging from 0.5 mm to 3.0 mm per axis). Physical voxel dimensions in millimeters are encoded in each image's NIfTI header. Team identifiers and case identifiers should be discovered programmatically from the data directory hierarchy.

## Evaluation Metrics

Four complementary metrics capture different clinically relevant aspects of segmentation quality. All metrics are computed on binarized masks where voxels with value > 0.5 are treated as foreground.

### Sørensen–Dice Coefficient (`dice`)

Measures voxel-level spatial overlap between predicted and ground truth binary masks. When both masks are entirely empty, the score is 1.0 (perfect agreement on absence of pathology).

### Absolute Volume Difference (`avd_ml`)

The absolute difference between predicted and true total lesion volumes, reported in milliliters. Volume computation must account for the physical voxel dimensions from the NIfTI header (recall: 1 mL = 1000 mm³).

### Lesion-wise F1 Score (`lesion_f1`)

An instance-level detection metric computed after identifying individual lesions via 3D connected component analysis using face-connectivity (6-connected neighborhood). A ground truth lesion is considered detected (true positive) if at least one predicted foreground voxel falls within its spatial extent. A predicted connected component with no ground truth overlap is a false positive. Undetected ground truth lesions are false negatives. When both masks contain zero lesion instances, the score is 1.0.

### Absolute Lesion Count Difference (`ald`)

The absolute difference in the number of distinct connected components between prediction and ground truth masks.

## Lesion Pattern Classification

Each ground truth case is classified into one of four categories based on its connected component morphology:

- **`no_lesion`**: No foreground voxels present
- **`single_vessel_infarct`**: The largest connected component comprises more than 95% of the total lesion voxel count
- **`scattered_infarcts`**: Three or more components present, AND either the largest constitutes less than 60% of total voxel count OR total lesion volume is below 5.0 mL
- **`mixed`**: All remaining cases

## Statistical Ranking and Analysis

Team rankings follow the rank-then-aggregate bootstrap methodology standard in MICCAI biomedical image analysis competitions (see supplementary ranking methodology document). Bootstrap sampling must be stratified by lesion pattern category to ensure each morphological subtype is proportionally represented in every iteration.

Pairwise statistical comparisons between consecutively ranked teams use two-sided Wilcoxon signed-rank tests on per-case Dice scores. With multiple simultaneous comparisons, appropriate family-wise error rate correction must be applied.

## Reference Code

A reference evaluation module from a prior ISLES edition is included for context. **Important**: consult the errata document for changes in the current edition's evaluation methodology before using any reference code.
