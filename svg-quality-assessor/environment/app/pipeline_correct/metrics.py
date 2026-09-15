import numpy as np
from skimage.metrics import structural_similarity


def compute_mse(img_a, img_b):
    """Mean Squared Error on float64 [0, 1] pixel arrays."""
    a = np.asarray(img_a, dtype=np.float64) / 255.0
    b = np.asarray(img_b, dtype=np.float64) / 255.0
    return float(np.mean((a - b) ** 2))


def compute_ssim(img_a, img_b):
    """Structural Similarity on float64 [0, 1] pixel arrays."""
    a = np.asarray(img_a, dtype=np.float64) / 255.0
    b = np.asarray(img_b, dtype=np.float64) / 255.0
    return float(
        structural_similarity(a, b, win_size=7, channel_axis=-1, data_range=1.0)
    )
