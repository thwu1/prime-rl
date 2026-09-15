# SVG Quality Metrics Specification

## 1. Rasterization

SVG strings are rasterized to 256x256 pixel RGB images using CairoSVG with a **white** background. On any rasterization failure, a solid white fallback image is produced.

Parameters:
- `output_width`: 256
- `output_height`: 256
- `background_color`: `"white"`
- Output format: RGB (3 channels), no alpha

## 2. Mean Squared Error (MSE)

Given two RGB images A and B, convert pixel values to float64 and normalize to [0, 1] by dividing by 255.0:

    MSE(A, B) = mean((A - B)^2)

The mean is taken over all pixels and all three RGB channels.

- Range: [0, 1]
- MSE = 0 for identical images

## 3. Structural Similarity Index (SSIM)

Computed on float64 arrays normalized to [0, 1]:

    SSIM(A, B) = structural_similarity(A, B, win_size=7, channel_axis=-1, data_range=1.0)

**Critical**: `data_range` must equal the dynamic range of the input arrays. Since arrays are normalized to [0, 1], `data_range=1.0`.

- Range: [-1, 1]
- SSIM = 1.0 for identical images

## 4. Color Histogram Intersection Distance

Measures perceptual color distribution similarity via histogram intersection in HSV color space.

### Algorithm:

1. Convert both RGB PIL images to HSV via `img.convert("HSV")`.
   PIL encodes all three HSV channels in [0, 255].

2. For each of the three channels (H=0, S=1, V=2), compute histograms:
   - Bins: 32 per channel
   - Range: [0, 256)
   - Use `numpy.histogram(channel.ravel(), bins=32, range=(0, 256))`

3. L1-normalize each histogram (divide by its sum, producing a distribution
   that sums to 1.0). If sum is zero, leave unchanged.

4. Histogram intersection for each channel:

       HI(h1, h2) = sum(min(h1[i], h2[i]))

5. Weighted similarity:

       similarity = 0.5 * HI_H + 0.3 * HI_S + 0.2 * HI_V

   Channel weights: H (hue) = 0.5, S (saturation) = 0.3, V (value) = 0.2.

6. Distance:

       distance = 1.0 - similarity

- Range: [0, 1]
- Distance = 0 for identical color distributions

## 5. Compression Ratio

    CR = max(1.0 - len_bytes(optimized) / len_bytes(original), 0.0)

Byte lengths are computed from UTF-8 encoded strings.

## 6. Quality Score

    Q = sqrt(SSIM) * (1 - sqrt(MSE)) * (1 - 0.3 * histogram_distance) * min(CR / target_fraction, 1.0)

Where:
- `target_fraction = target_compression_pct / 100.0`
- If `target_fraction <= 0`, use `1e-10`
- `CR` is clamped: `max(CR, 0.0)`

## 7. Quality Tiers

| Tier      | Condition   |
|-----------|-------------|
| excellent | Q >= 0.8    |
| good      | Q >= 0.6    |
| fair      | Q >= 0.4    |
| poor      | Q < 0.4     |

Applied in order (first match wins).
