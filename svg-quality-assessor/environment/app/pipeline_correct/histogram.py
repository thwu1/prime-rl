import numpy as np


def compute_histogram_distance(img_a, img_b):
    """Color histogram intersection distance in HSV space.

    Converts images to HSV, computes L1-normalized histograms for each channel,
    measures histogram intersection similarity with channel weights
    H=0.5, S=0.3, V=0.2, and returns 1 - weighted_similarity.
    """
    hsv_a = np.array(img_a.convert("HSV"))
    hsv_b = np.array(img_b.convert("HSV"))

    weights = [0.5, 0.3, 0.2]
    similarity = 0.0

    for ch in range(3):
        hist_a, _ = np.histogram(hsv_a[:, :, ch].ravel(), bins=32, range=(0, 256))
        hist_b, _ = np.histogram(hsv_b[:, :, ch].ravel(), bins=32, range=(0, 256))

        ha = hist_a.astype(np.float64)
        hb = hist_b.astype(np.float64)

        sum_a = ha.sum()
        sum_b = hb.sum()

        if sum_a > 0:
            ha /= sum_a
        if sum_b > 0:
            hb /= sum_b

        hi = float(np.minimum(ha, hb).sum())
        similarity += weights[ch] * hi

    return float(1.0 - similarity)
