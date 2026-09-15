# ISLES-26 Challenge Evaluation Protocol

## Overview

This document specifies the evaluation methodology for the ISLES-26 Ischemic Stroke Lesion Segmentation Challenge. Automated segmentation algorithms are evaluated on binary infarct mask predictions against expert-annotated ground truth masks using multiple complementary metrics that balance voxel-level accuracy with clinically relevant instance-level detection performance.

## Data Format

All images are NIfTI-1 format (`.nii.gz`). Physical voxel dimensions (in millimeters) are encoded in each image header and vary across cases. Team identifiers and case identifiers should be discovered from the data directory structure.

## Evaluation Metrics

Four metrics are computed per team per case:

### Sørensen–Dice Coefficient (`dice`)

Measures voxel-level spatial overlap between the predicted and ground truth binary masks. The coefficient is defined as twice the intersection cardinality divided by the sum of both masks' cardinalities. When both masks are entirely empty, the score is 1.0.

### Absolute Volume Difference (`avd_ml`)

The absolute difference between predicted and true total lesion volumes, reported in milliliters. Volume is computed from voxel counts using the per-axis voxel dimensions stored in the NIfTI header. Note that NIfTI voxel dimensions are conventionally in millimeters and 1 mL = 1000 mm³.

### Lesion-wise F1 Score (`lesion_f1`)

An instance-level detection metric. Individual lesions are isolated by 3D connected component analysis using face-connectivity (6-connected neighborhood in 3D). A ground truth lesion is considered successfully detected (true positive) if at least one predicted voxel falls within its spatial extent. A predicted connected component that does not overlap any ground truth lesion is counted as a false positive. Ground truth lesions with no overlapping predicted voxels are false negatives. The F1 score is then computed from the resulting TP, FP, and FN counts. When both masks contain zero lesion instances, the score is 1.0.

### Absolute Lesion Count Difference (`ald`)

The absolute difference in the number of distinct connected components between prediction and ground truth masks, using the same connected component labeling as the lesion-wise F1 score.

## Lesion Pattern Classification

Each ground truth case is classified into one of four clinical stroke pattern categories based on its connected component structure:

- **`no_lesion`**: No foreground voxels present in the ground truth mask.
- **`single_vessel_infarct`**: The largest connected component comprises more than 95% of the total lesion voxel count.
- **`scattered_infarcts`**: Three or more lesion components are present, AND either (a) the largest component constitutes less than 60% of the total lesion voxel count OR (b) the total lesion volume is below 5.0 mL.
- **`mixed`**: All remaining cases not fitting any of the above categories.

Classification categories are evaluated on ground truth masks only.

## Statistical Ranking

Team rankings follow the "rank then aggregate" methodology standard in MICCAI biomedical challenges.

A bootstrap resampling procedure with **1000 iterations** and **random seed 42** assesses ranking stability. In each iteration, N cases are sampled with replacement. For each of the four metrics, teams are ranked on their mean scores over the sampled cases (rank 1 = best). For Dice and lesion-wise F1, higher values indicate better performance; for AVD and ALD, lower values are better. Ties receive the average of the ranks they span.

Each team's combined rank in an iteration is the arithmetic mean of its four per-metric ranks. The final ordering is determined by the mean combined rank across all iterations (ascending — lowest mean rank = best). Report the fraction of iterations in which each team achieved the best (lowest) combined rank.

## Pairwise Significance Testing

For each consecutive pair in the final ranking order (1st vs 2nd, 2nd vs 3rd, etc.), compute a two-sided Wilcoxon signed-rank test on per-case Dice scores and report the p-value.

## Notes

- A reference evaluation script (`reference_eval.py`) from a prior ISLES edition is included in this directory for context. It depends on the `panoptica` library and uses IoU-threshold matching for lesion detection. **The current challenge protocol uses the simpler any-voxel-overlap detection criterion described above**, not IoU-threshold matching. Treat the reference as background context, not as the authoritative implementation.
- Metrics should be computed on binarized masks (voxels > 0.5 are foreground).
