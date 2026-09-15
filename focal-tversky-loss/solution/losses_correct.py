
"""
Correct implementation of FocalTverskyLoss.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Union, Sequence


class FocalTverskyLoss(nn.Module):
    """
    Focal Tversky Loss for multi-class medical image segmentation.

    Combines the Tversky similarity index with focal modulation to handle
    class imbalance, particularly for small structures in medical images.
    """

    def __init__(
        self,
        alpha: float = 0.7,
        beta: float = 0.3,
        gamma: float = 0.75,
        smooth: float = 1.0,
        include_background: bool = True,
        to_onehot_y: bool = False,
        sigmoid: bool = False,
        softmax: bool = False,
        weight: Optional[Union[Sequence[float], torch.Tensor]] = None,
        batch: bool = False,
        reduction: str = "mean",
    ):
        super().__init__()
        if sigmoid and softmax:
            raise ValueError(
                "sigmoid and softmax are mutually exclusive — set at most one to True."
            )
        if reduction not in ("mean", "sum", "none"):
            raise ValueError(
                f"reduction must be 'mean', 'sum', or 'none', got '{reduction}'."
            )

        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.smooth = smooth
        self.include_background = include_background
        self.to_onehot_y = to_onehot_y
        self.do_sigmoid = sigmoid
        self.do_softmax = softmax
        self.batch = batch
        self.reduction = reduction

        if weight is not None:
            self.register_buffer(
                "weight", torch.as_tensor(weight, dtype=torch.float32)
            )
        else:
            self.weight = None

    def forward(self, input: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        num_classes = input.shape[1]

        # Step 1 — Activation
        if self.do_sigmoid:
            p = torch.sigmoid(input)
        elif self.do_softmax:
            p = torch.softmax(input, dim=1)
        else:
            p = input

        # Step 2 — One-hot encoding
        if self.to_onehot_y:
            t = target.squeeze(1).long()
            g = F.one_hot(t, num_classes)
            # (B, *spatial, C) → (B, C, *spatial)
            perm = [0, len(g.shape) - 1] + list(range(1, len(g.shape) - 1))
            g = g.permute(*perm).float()
        else:
            g = target.float()

        # Step 3 — Background exclusion
        if not self.include_background:
            p = p[:, 1:]
            g = g[:, 1:]

        # Step 4 — Reduction axes
        if self.batch:
            reduce_dims = [0] + list(range(2, p.dim()))
        else:
            reduce_dims = list(range(2, p.dim()))

        tp = (p * g).sum(dim=reduce_dims)
        fp = (p * (1 - g)).sum(dim=reduce_dims)
        fn = ((1 - p) * g).sum(dim=reduce_dims)

        # Step 5 — Tversky Index
        ti = (tp + self.smooth) / (
            tp + self.alpha * fp + self.beta * fn + self.smooth
        )

        # Step 6 — Focal modulation
        ftl = (1.0 - ti) ** self.gamma

        # Step 7 — Class weighting
        if self.weight is not None:
            ftl = ftl * self.weight

        # Step 8 — Reduction
        if self.reduction == "mean":
            return ftl.mean()
        elif self.reduction == "sum":
            return ftl.sum()
        else:
            return ftl
