import numpy as np


def compute_histogram_distance(img_a, img_b):
    """Color histogram distance between two images.

    See /app/spec/methodology.md for the evaluation methodology.
    """
    arr_a = np.array(img_a)
    arr_b = np.array(img_b)

    weights = [0.5, 0.3, 0.2]
    similarity = 0.0

    for ch in range(3):
        hist_a, _ = np.histogram(arr_a[:, :, ch].ravel(), bins=32, range=(0, 256))
        hist_b, _ = np.histogram(arr_b[:, :, ch].ravel(), bins=32, range=(0, 256))

        ha = hist_a.astype(np.float64)
        hb = hist_b.astype(np.float64)

        sum_a = ha.sum()
        sum_b = hb.sum()

        if sum_a > 0:
            ha /= sum_a
        if sum_b > 0:
            hb /= sum_b

        bc = float(np.sum(np.sqrt(ha * hb)))
        similarity += weights[ch] * bc

    return float(1.0 - similarity)
