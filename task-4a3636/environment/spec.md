# NFIQ2-Compatible Quality Feature Extraction Specification

This document specifies the algorithms for computing fingerprint image quality
features compatible with NIST NFIQ 2. All images are 8-bit grayscale, 320x320
pixels.

## 1. PGM Image Format

Read binary PGM (P5) files. Format: ASCII header `P5\n<width> <height>\n255\n`
followed by `width * height` raw bytes (row-major, top-to-bottom).

## 2. Parameters

| Parameter | Value |
|-----------|-------|
| Block size (BS) | 32 pixels |
| Slanted block width (SBW) | 32 pixels |
| Slanted block height (SBH) | 16 pixels |
| Ridge segmentation threshold | 0.1 |
| Histogram bin boundaries | 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9 |

## 3. Numerical Gradient Computation

Given a 2D grayscale image `I` (float64), compute gradients `gx` (X-direction)
and `gy` (Y-direction).

**X-gradient** (`gx`):
- First column: `gx[y, 0] = I[y, 1] - I[y, 0]` (forward difference)
- Interior: `gx[y, x] = (I[y, x+1] - I[y, x-1]) / 2` (central difference)
- Last column: `gx[y, W-1] = I[y, W-1] - I[y, W-2]` (backward difference)

**Y-gradient** (`gy`): Compute the X-gradient of the transposed image, then
transpose the result. Equivalently:
- First row: `gy[0, x] = I[1, x] - I[0, x]`
- Interior: `gy[y, x] = (I[y+1, x] - I[y-1, x]) / 2`
- Last row: `gy[H-1, x] = I[H-1, x] - I[H-2, x]`

## 4. Ridge Segmentation

Determines which image blocks contain fingerprint ridges.

1. Convert image to float64: `im = float64(image)`
2. Normalize to zero mean, unit standard deviation:
   `im = (im - mean(im)) / std(im)`
3. For each non-overlapping BS x BS block:
   - Compute the standard deviation of the normalized block
   - Replace all pixels in the block with this std value
4. Create binary mask: `mask = (stddev_image > threshold)`

Where `threshold = 0.1`. The mask has the same dimensions as the image; a pixel
is foreground (1/True) if its block's std exceeds the threshold.

## 5. Covariance Coefficients and Ridge Orientation

For a BS x BS image block, compute gradient covariance:

1. Compute gradients `gx`, `gy` of the block (Section 3)
2. `a = mean(gx^2)` — mean of squared X-gradient
3. `b = mean(gy^2)` — mean of squared Y-gradient
4. `c = mean(gx * gy)` — mean of gradient product

Ridge orientation angle:
```
theta = atan2(c, a - b) / 2
```

## 6. Orientation Certainty Level (OCL)

Measures the strength of the dominant ridge orientation per block.

**Block iteration**: Divide image into non-overlapping BS x BS blocks. Only
process blocks where both dimensions are exactly BS (skip partial edge blocks).

**Per-block computation**:
1. Compute numerical gradients of the block (Section 3, operating on the
   uint8 pixel values cast to float64)
2. Compute covariance: `a = mean(gx^2)`, `b = mean(gy^2)`, `c = mean(gx*gy)`
3. Compute eigenvalues:
   - `eigv_max = ((a + b) + sqrt((a - b)^2 + 4*c^2)) / 2`
   - `eigv_min = ((a + b) - sqrt((a - b)^2 + 4*c^2)) / 2`
4. If `eigv_max == 0`: **exclude** block (do not add to results)
5. `OCL = 1.0 - eigv_min / eigv_max`

Collect all valid OCL values into a list. Compute histogram, mean, and stddev
(Section 9).

## 7. Frequency Domain Analysis (FDA)

Analyzes ridge-valley periodicity via DFT of projected ridge profiles.

### 7.1 Block Geometry

The FDA uses an offset grid to allow extraction of rotated slanted blocks:

```
eblksz = ceil(sqrt(SBW^2 + SBH^2))     # = ceil(sqrt(1280)) = 36
diff = eblksz - BS                       # = 4
blkoffset = ceil(diff / 2)              # = 2
mapRows = floor((H - diff) / BS)        # = floor(316/32) = 9
mapCols = floor((W - diff) / BS)        # = 9
```

Iterate blocks: `r` from `blkoffset` to `H - BS - blkoffset` (inclusive),
step BS. Similarly for `c`. This yields a 9x9 grid of block positions.

### 7.2 Per-Block FDA Computation

For each block position `(r, c)`:

1. Extract 32x32 region `im_roi = image[r:r+BS, c:c+BS]`
2. Check mask: all pixels in `mask[r:r+BS, c:c+BS]` must be foreground.
   If not, skip block.
3. Compute orientation `theta` from `im_roi` (Section 5)
4. Extract overlapping window:
   `blkw = image[r-blkoffset : r+BS+blkoffset, c-blkoffset : c+BS+blkoffset]`
   (this is a 36x36 block)
5. **Rotate** `blkw` counter-clockwise by `(theta + pi/2)` radians about its
   center, using **nearest-neighbor** interpolation. Output size equals input
   size (36x36). Pixels outside the source image become 0.
6. **Crop slanted block**: From the 36x36 rotated block, extract a 32x16
   (SBW x SBH) region centered within it:
   ```
   center = 36 // 2   # = 18
   xoff = SBW // 2    # = 16
   yoff = SBH // 2    # = 8
   row_start = center - (xoff - 1) - 1  # = 18 - 15 - 1 = 2
   row_end   = center + xoff             # = 34
   col_start = center - (yoff - 1) - 1  # = 18 - 7 - 1 = 10
   col_end   = center + yoff             # = 26
   crop = rotated[2:34, 10:26]           # 32 rows, 16 cols
   ```

7. **Row means**: For each row of the 32x16 crop, compute the mean of its 16
   pixel values. This gives a 1D profile of length 32.
8. **1D DFT**: Compute the DFT of the 32-element profile. Use zero-padding to
   the next optimal DFT size if needed (32 is already optimal: 2^5).
9. **Magnitude spectrum**: Compute the magnitude of each DFT coefficient.
   Exclude the DC component (index 0). The remaining spectrum has 31 elements
   (indices 1..31 in the DFT output).
10. **FDA score**:
    - Find the peak magnitude `mVal` at index `mLoc` (within the 31-element
      DC-excluded spectrum, so `mLoc` is 0-based in this sub-array)
    - If `mLoc == 0` or `mLoc >= 30`: score = 1.0
    - Compute denominator: sum of the first `floor(31/2) = 15` elements of the
      DC-excluded spectrum (i.e., indices 0..14, corresponding to the lower
      half of frequencies)
    - `score = (mVal + 0.3 * (spectrum[mLoc-1] + spectrum[mLoc+1])) / denominator`

Collect all FDA scores. Compute histogram, mean, and stddev (Section 9).

## 8. Contrast Features (Mu and MMB)

**Mu**: Arithmetic mean of all pixel values in the image (uint8 values).

**MMB** (Mean of Block Means): Divide the image into BS x BS blocks. Include
partial blocks at the right and bottom edges (unlike OCL which skips them). For
each block, compute the mean pixel value. MMB is the arithmetic mean of all
block means.

## 9. Histogram Binning

Given a list of quality values and 9 bin boundaries
`B = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]`, produce a 10-bin
histogram:

1. Append `+infinity` to boundaries: `B' = [0.1, 0.2, ..., 0.9, +inf]`
2. Sort the quality values in ascending order
3. Initialize 10 bins to 0
4. For each value, assign to the first bin `i` where `value < B'[i]`:
   - Bin 0: `value < 0.1`
   - Bin 1: `0.1 <= value < 0.2`
   - ...
   - Bin 9: `value >= 0.9`
5. Histogram values are integer counts

Also compute the **mean** and **standard deviation** (population stddev using
ddof=0 for matching behavior, but with Bessel's correction ddof=1 in the
original) of the quality values.

Note: use `ddof=1` (sample standard deviation / Bessel's correction) for
stddev computation to match the reference implementation.

## 10. Output Format

Write `/app/output.json` with the following structure. Image keys are filenames
without the `.pgm` extension. All floating-point values should have full
precision (not rounded). Histogram values are integers.

```json
{
  "uniform": {
    "mu": <float>,
    "mmb": <float>,
    "ocl": {
      "histogram": [<int>, ..., <int>],
      "mean": <float>,
      "stddev": <float>
    },
    "fda": {
      "histogram": [<int>, ..., <int>],
      "mean": <float>,
      "stddev": <float>
    }
  },
  "diagonal": { ... },
  "degraded": { ... }
}
```
