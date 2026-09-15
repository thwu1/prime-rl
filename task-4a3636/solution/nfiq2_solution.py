#!/usr/bin/env python3
"""
Corrected NFIQ2-compatible quality feature extraction.

Fixes applied to the buggy implementation:
1. FDA rotation: Added + pi/2 offset to align ridges before DFT analysis
   (Reference: fda.cpp line ~286: orientation + (M_PI / 2))
2. FDA crop: Corrected xoff/yoff assignment in slanted block extraction
   (Reference: fda.cpp lines 300-302: Range uses xoff for rows, yoff for cols)
3. OCL discriminant: Fixed to use c**2 instead of c in eigenvalue formula
   (Reference: ocl.cpp line 177: pow(c, 2))

"""
import json
import math
import os

import numpy as np
from scipy.ndimage import rotate as scipy_rotate

# Block and slanted block parameters
BS = 32
SBW = 32
SBH = 16
RIDGE_THRESH = 0.1
HIST_BOUNDARIES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]


def read_pgm(filepath):
    """Read a binary PGM (P5) file, return 2D numpy array (uint8)."""
    with open(filepath, 'rb') as f:
        magic = f.readline().strip()
        assert magic == b'P5', f"Expected P5, got {magic}"
        line = f.readline()
        while line.startswith(b'#'):
            line = f.readline()
        w, h = map(int, line.split())
        maxval = int(f.readline().strip())
        assert maxval == 255
        data = f.read(w * h)
        img = np.frombuffer(data, dtype=np.uint8).reshape((h, w))
    return img


def numerical_gradient_x(img):
    """Compute gradient in X direction using finite differences."""
    out = np.zeros_like(img, dtype=np.float64)
    out[:, 0] = img[:, 1].astype(np.float64) - img[:, 0].astype(np.float64)
    out[:, 1:-1] = (img[:, 2:].astype(np.float64) - img[:, :-2].astype(np.float64)) / 2.0
    out[:, -1] = img[:, -1].astype(np.float64) - img[:, -2].astype(np.float64)
    return out


def numerical_gradients(img):
    """Compute X and Y gradients of a 2D image."""
    img_f = img.astype(np.float64) if img.dtype != np.float64 else img
    gx = numerical_gradient_x(img_f)
    gy = numerical_gradient_x(img_f.T).T
    return gx, gy


def ridge_segment(img, blksize, thresh):
    """Segment image into ridge (foreground) and background regions."""
    h, w = img.shape
    im = img.astype(np.float64)
    mu = im.mean()
    sigma = im.std()
    if sigma == 0:
        return np.zeros((h, w), dtype=bool)
    im = (im - mu) / sigma
    stddev_img = np.zeros_like(im)
    for r in range(0, h, blksize):
        for c in range(0, w, blksize):
            rend = min(r + blksize, h)
            cend = min(c + blksize, w)
            block = im[r:rend, c:cend]
            s = block.std()
            stddev_img[r:rend, c:cend] = s
    mask = stddev_img > thresh
    return mask


def covcoef(block):
    """Compute gradient covariance coefficients a, b, c for a block."""
    gx, gy = numerical_gradients(block)
    a = np.mean(gx ** 2)
    b = np.mean(gy ** 2)
    c = np.mean(gx * gy)
    return a, b, c


def ridge_orient(a, b, c):
    """Compute ridge orientation from covariance coefficients."""
    return math.atan2(c, a - b) / 2.0


def compute_ocl(img):
    """Compute OCL for all full BS x BS blocks."""
    h, w = img.shape
    values = []
    for i in range(0, h, BS):
        for j in range(0, w, BS):
            if i + BS > h or j + BS > w:
                continue
            block = img[i:i+BS, j:j+BS]
            gx, gy = numerical_gradients(block)
            a = np.mean(gx ** 2)
            b = np.mean(gy ** 2)
            c = np.mean(gx * gy)
            # FIX 3: Use c**2, not c, in discriminant
            disc = math.sqrt((a - b) ** 2 + 4.0 * c ** 2)
            eigv_max = ((a + b) + disc) / 2.0
            eigv_min = ((a + b) - disc) / 2.0
            if eigv_max == 0:
                continue
            ocl = 1.0 - eigv_min / eigv_max
            values.append(ocl)
    return values


def allfun(mask_block):
    """Returns True if all elements are nonzero/True."""
    return np.all(mask_block)


def rotate_block(block, angle_rad):
    """Rotate block CCW by angle_rad, nearest-neighbor, same output size."""
    angle_deg = math.degrees(angle_rad)
    rotated = scipy_rotate(block.astype(np.float64), angle_deg,
                           order=0, reshape=False, mode='constant', cval=0.0)
    return rotated


def fda_single(block36, orientation):
    """Compute FDA score for a 36x36 overlapping block."""
    # FIX 1: Add pi/2 offset to rotation angle
    rotated = rotate_block(block36, orientation + math.pi / 2.0)

    center = 18
    xoff = SBW // 2   # 16
    yoff = SBH // 2   # 8

    # FIX 2: Use xoff for rows, yoff for cols (matching C++ reference)
    row_start = center - (xoff - 1) - 1  # 2
    row_end = center + xoff               # 34
    col_start = center - (yoff - 1) - 1  # 10
    col_end = center + yoff               # 26
    cropped = rotated[row_start:row_end, col_start:col_end]  # 32x16

    profile = cropped.mean(axis=1)
    dft = np.fft.fft(profile)
    magnitude = np.abs(dft)
    amp = magnitude[1:]

    if len(amp) == 0:
        return 0.0

    m_loc = int(np.argmax(amp))
    m_val = amp[m_loc]

    if m_loc == 0 or m_loc + 1 >= len(amp):
        return 1.0

    denom_len = len(amp) // 2
    denom = np.sum(amp[:denom_len])

    if denom == 0:
        return 0.0

    score = (m_val + 0.3 * (amp[m_loc - 1] + amp[m_loc + 1])) / denom
    return float(score)


def compute_fda(img, mask):
    """Compute FDA for all valid blocks on the offset grid."""
    h, w = img.shape
    img_f = img.astype(np.float64)
    eblksz = math.ceil(math.sqrt(SBW**2 + SBH**2))
    diff = eblksz - BS
    blkoffset = math.ceil(diff / 2)
    values = []
    r = blkoffset
    while r < h - (BS + blkoffset - 1):
        c = blkoffset
        while c < w - (BS + blkoffset - 1):
            im_roi = img_f[r:min(r+BS, h), c:min(c+BS, w)]
            mask_roi = mask[r:min(r+BS, h), c:min(c+BS, w)]
            if allfun(mask_roi):
                a, b, cc = covcoef(im_roi)
                theta = ridge_orient(a, b, cc)
                r_start = r - blkoffset
                r_end = min(r + BS + blkoffset, h)
                c_start = c - blkoffset
                c_end = min(c + BS + blkoffset, w)
                blkw = img_f[r_start:r_end, c_start:c_end]
                score = fda_single(blkw, theta)
                values.append(score)
            c += BS
        r += BS
    return values


def compute_mu(img):
    """Global mean of pixel values."""
    return float(np.mean(img.astype(np.float64)))


def compute_mmb(img):
    """Mean of block means (including partial edge blocks)."""
    h, w = img.shape
    means = []
    for i in range(0, h, BS):
        for j in range(0, w, BS):
            block = img[i:min(i+BS, h), j:min(j+BS, w)]
            means.append(float(np.mean(block.astype(np.float64))))
    return float(np.mean(means))


def histogram_bin(values, boundaries=None):
    """Bin values into 10 bins with given boundaries."""
    if boundaries is None:
        boundaries = list(HIST_BOUNDARIES)
    n = len(values)
    if n == 0:
        return [0] * 10, 0.0, 0.0
    sorted_vals = sorted(values)
    bins_bounds = boundaries + [float('inf')]
    bins = [0] * 10
    bucket = 0
    bound = bins_bounds[bucket]
    for v in sorted_vals:
        while not math.isinf(v) and v >= bound:
            bucket += 1
            bound = bins_bounds[bucket]
        bins[bucket] += 1
    mean_val = float(np.mean(values))
    std_val = float(np.std(values, ddof=1)) if n > 1 else 0.0
    return bins, mean_val, std_val


def process_image(filepath):
    """Process a single image and return its feature dict."""
    img = read_pgm(filepath)
    mask = ridge_segment(img, BS, RIDGE_THRESH)
    mu = compute_mu(img)
    mmb = compute_mmb(img)
    ocl_values = compute_ocl(img)
    ocl_hist, ocl_mean, ocl_std = histogram_bin(ocl_values)
    fda_values = compute_fda(img, mask)
    fda_hist, fda_mean, fda_std = histogram_bin(fda_values)
    return {
        "mu": mu,
        "mmb": mmb,
        "ocl": {"histogram": ocl_hist, "mean": ocl_mean, "stddev": ocl_std},
        "fda": {"histogram": fda_hist, "mean": fda_mean, "stddev": fda_std},
    }


def main():
    images_dir = "/app/images"
    output_path = "/app/output.json"
    results = {}
    for fname in sorted(os.listdir(images_dir)):
        if not fname.endswith('.pgm'):
            continue
        name = fname[:-4]
        filepath = os.path.join(images_dir, fname)
        results[name] = process_image(filepath)
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Wrote features to {output_path}")


if __name__ == '__main__':
    main()
