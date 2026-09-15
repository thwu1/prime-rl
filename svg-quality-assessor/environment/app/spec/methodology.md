# SVG Optimization Quality Evaluation

## Rasterization

SVGs are rasterized to 256x256 RGB images using CairoSVG with a white
background. White is the standard web rendering default; SVG content with
transparent regions composites against this background via source-over
alpha blending. On failure, a solid white fallback image is produced.

## Metrics

### MSE (Mean Squared Error)

Float64 pixel arrays normalized to [0, 1] (divide by 255):

    MSE(A, B) = mean((A - B)^2)

The mean is taken over all pixels and all RGB channels. Squaring
emphasizes large pixel differences over small ones; this is critical
because human perception is more sensitive to large localized errors
than to uniformly distributed small errors. Do not confuse MSE with
Mean Absolute Error (MAE), which uses absolute differences rather than
squared differences and has different sensitivity characteristics.

Range [0, 1], zero for identical images.

### SSIM (Structural Similarity Index)

Gaussian-weighted structural similarity (Wang, Bovik, Sheikh, Simoncelli,
IEEE TIP 2004) on normalized [0, 1] float64 arrays, 7x7 window,
multichannel.

The implementation must use Gaussian-weighted local statistics, not a
uniform (box) window. Gaussian weighting models the fovea's spatial
sensitivity profile: the center of each local patch contributes more to
the similarity measurement than the periphery, matching how the human
visual system evaluates local image quality. Using a uniform window
over-weights peripheral pixels and underestimates the perceptual impact
of central distortions.

The data_range parameter must equal the actual dynamic range of the input
arrays -- the difference between the maximum and minimum possible pixel
values. For arrays normalized to [0, 1], data_range = 1.0. Setting
data_range to 255 when the input data spans [0, 1] causes the stability
constants C1 and C2 to dominate, collapsing SSIM toward 1.0 for all
input pairs regardless of actual similarity.

Range [-1, 1], 1.0 for identical images.

### Color Histogram Distance

Histogram intersection distance in HSV color space. The HSV decomposition
is chosen because it separates chromatic content (Hue, Saturation) from
achromatic intensity (Value), allowing the weighting scheme to
independently control the influence of color shifts versus brightness
changes. Computing histograms directly in RGB conflates chromatic and
achromatic information, making the per-channel weights semantically
meaningless.

Algorithm:
1. Convert both images to HSV (PIL mode, all channels [0, 255]).
2. Compute 32-bin histograms per channel over [0, 256).
3. L1-normalize each histogram to a probability distribution.
4. Compute intersection: HI(h1, h2) = sum(min(h1[i], h2[i])).
5. Weighted similarity: sim = 0.5 * HI_H + 0.3 * HI_S + 0.2 * HI_V.
6. Distance = 1 - sim.

The histogram intersection metric measures the overlap between two
distributions and is bounded in [0, 1] after normalization. It is
preferred over divergence-based measures (e.g. Bhattacharyya coefficient,
which uses geometric means of bin pairs) because intersection has a
direct interpretation as the proportion of shared color content and is
robust to zero-bins without requiring smoothing.

Range [0, 1], zero for identical color distributions.

## Compression

CR = max(1 - optimized_bytes / original_bytes, 0). Byte lengths from
UTF-8 encoding. Target met when CR >= target_pct / 100.

## Quality Score

Q = sqrt(SSIM) * (1 - sqrt(MSE)) * (1 - 0.3 * hist_dist) * min(CR / target_frac, 1.0)

target_frac = target_pct / 100; if <= 0 use 1e-10.

The multiplicative formulation ensures that catastrophic failure in any
single quality dimension cannot be compensated by good performance in
others. The square root transforms on SSIM and MSE map these metrics
into perceptually more linear scales before combination.

## Tiers

excellent >= 0.8, good >= 0.6, fair >= 0.4, poor < 0.4.

## Output

Samples in input order. Aggregates: arithmetic means of all metrics,
target hit rate, tier counts, total samples.
