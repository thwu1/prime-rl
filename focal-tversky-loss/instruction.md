The project at `/app/` implements a 3D medical image segmentation system with two interrelated components containing multiple interacting defects.

## Loss Function (`/app/losses.py`)

`FocalTverskyLoss` has a correct constructor but its `forward()` method contains multiple bugs — incorrect tensor operations for certain spatial dimensionalities, missing symmetry in channel exclusion, and a mathematical error in the core formula. The mathematical specification is in `/app/spec.md`. The implementation must produce correct values for every parameter combination and work with inputs of any spatial rank (2D, 3D, or higher).

## Evaluation Pipeline (`/app/pipeline.py`)

The MONAI-based pipeline has interacting defects across data preprocessing, model architecture, and inference configuration. It provides functions for synthetic data generation, preprocessing transforms, model creation, standalone evaluation, and training with evaluation. The `train_and_evaluate()` function uses the `FocalTverskyLoss` from `losses.py`, coupling both components — both must be correct for training to converge.

When all defects are fixed:
- Loss values match the mathematical specification for all parameter combinations and spatial ranks
- Transforms produce single-channel tensors of shape `(1, D, H, W)` with values in `[0, 1]`
- The model accepts 3D volumetric inputs (B x C x D x H x W) and preserves spatial dimensions
- Training shows decreasing loss and the trained model achieves non-zero Dice
- Standalone evaluation completes and returns a valid, non-NaN Dice score