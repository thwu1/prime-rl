# Focal Tversky Loss — Mathematical Specification

**Reference**: Abraham, N. & Khan, N.M. (2019). "A Novel Focal Tversky Loss Function with Improved Attention U-Net for Lesion Segmentation." *ISBI 2019*.

## Notation

| Symbol | Domain | Description |
|--------|--------|-------------|
| X | R^{B x C x S_1 x ... x S_k} | Raw model output (logits) |
| P | [0,1]^{B x C x S_1 x ... x S_k} | Predicted probabilities (post-activation) |
| G | {0,1}^{B x C x S_1 x ... x S_k} | Ground truth (binary, one-hot across C) |
| alpha, beta | R+ | False-positive / false-negative penalty weights |
| gamma | R+ | Focal exponent |
| epsilon | R+ | Smoothing constant |

## Formulation

**Activation**: At most one mode may be active.

    P = sigmoid(X)          (element-wise sigmoid)
    P = softmax(X, dim=1)   (per-voxel softmax across classes)
    P = X                   (assume pre-activated)

**Target Encoding**: When targets arrive as integer class labels
Y in {0,...,C-1}^{B x 1 x S_1 x ... x S_k}, they must be converted to binary
one-hot representation G in {0,1}^{B x C x S_1 x ... x S_k} with the class
axis at dimension 1. This conversion must generalize to arbitrary spatial
rank k >= 1.

**Background Exclusion**: When enabled, channel index 0 (background class) is
removed from **both** P and G before computing the loss, so background does
not contribute to any term.

**Tversky Index** (per class c, optionally per sample b):

    TP_c = sum( P_c * G_c )
    FP_c = sum( P_c * (1 - G_c) )
    FN_c = sum( (1 - P_c) * G_c )

    TI_c = (TP_c + epsilon) / (TP_c + alpha * FP_c + beta * FN_c + epsilon)

Summation domains:
- Per-sample mode: spatial dimensions only -> TI in R^{B x C'}
- Batch mode: batch AND spatial dimensions jointly -> TI in R^{C'}

where C' is the number of classes after optional background exclusion.

**Focal Modulation**:

    FTL_c = (1 - TI_c) ^ gamma

**Class Weighting**: When a weight vector w is provided:

    FTL_c <- w_c * FTL_c

**Reduction**: `mean` (average all elements), `sum`, or `none` (return tensor).

## Key Properties

- alpha = beta = 0.5 with gamma = 1 recovers soft Dice loss
- gamma = 0 implies FTL_c = 1.0 for all c regardless of prediction quality
- Higher alpha increases precision emphasis; higher beta increases recall emphasis
- Must support inputs with arbitrary spatial rank k >= 1
- Gradients must be finite and non-NaN for all valid inputs
