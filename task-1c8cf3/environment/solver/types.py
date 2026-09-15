
from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class AffineParams:
    """Affine depth correction parameters.

    True depth = a * predicted_depth + b
    Normalized so that a1 = 1.0 (view 1 scale fixed).
    """
    a1: float  # Always 1.0 (normalization)
    b1: float  # Shift for view 1
    a2: float  # Relative scale for view 2
    b2: float  # Shift for view 2


@dataclass
class PoseResult:
    """Relative pose estimation result.

    The transformation takes points from view 1 to view 2:
    X2 = R @ X1 + t
    """
    R: np.ndarray         # (3,3) rotation matrix
    t: np.ndarray         # (3,) translation vector
    affine: AffineParams  # Recovered affine parameters
    inlier_mask: Optional[np.ndarray] = None  # Boolean mask of inliers
