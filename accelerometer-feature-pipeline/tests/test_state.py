"""
Test suite for accelerometer data processing pipeline.
Generates synthetic walking data with known sensor calibration errors,
runs the two-stage pipeline (calibration + feature extraction) via make,
and validates each of 44 features against an independent Python reference.

"""

import pytest
import numpy as np
import json
import subprocess
import os

SAMPLE_RATE = 100

# Known calibration parameters (must match /app/config/calibration.properties)
CALIB_OFFSET = [0.08, -0.12, 0.05]
CALIB_SCALE = [1.02, 0.98, 1.015]


# ============================================================
# Data generation
# ============================================================

def generate_test_data():
    """Generate deterministic synthetic walking-pattern accelerometer data
    with known sensor calibration errors applied."""
    np.random.seed(42)
    n = 3000  # 30 seconds at 100Hz
    t = np.arange(n) / float(SAMPLE_RATE)

    step_freq = 2.0
    intensity = 0.3

    # Ideal (correctly calibrated) signals
    x = intensity * np.sin(2 * np.pi * step_freq * t) + np.random.normal(0, 0.05, n)
    y = -0.8 + intensity * 0.3 * np.cos(2 * np.pi * step_freq * t) + np.random.normal(0, 0.05, n)
    z = 0.6 + intensity * 0.2 * np.sin(2 * np.pi * step_freq * 0.5 * t) + np.random.normal(0, 0.05, n)

    # Higher-frequency motion components (muscle tremor, impact dynamics)
    x += 0.08 * np.sin(2 * np.pi * 12 * t)
    z += 0.05 * np.cos(2 * np.pi * 15 * t)

    x_ideal, y_ideal, z_ideal = x.copy(), y.copy(), z.copy()

    # Apply inverse calibration to create raw sensor readings
    # If calibrated = (raw - offset) * scale, then raw = calibrated / scale + offset
    x_raw = x_ideal / CALIB_SCALE[0] + CALIB_OFFSET[0]
    y_raw = y_ideal / CALIB_SCALE[1] + CALIB_OFFSET[1]
    z_raw = z_ideal / CALIB_SCALE[2] + CALIB_OFFSET[2]

    return x_raw, y_raw, z_raw, x_ideal, y_ideal, z_ideal


def save_csv(x, y, z, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        for i in range(len(x)):
            f.write(f"{x[i]:.17g},{y[i]:.17g},{z[i]:.17g}\n")


# ============================================================
# Reference implementation (correct algorithms)
# ============================================================

def ref_mean(vals):
    return np.mean(vals)


def ref_range(vals):
    return np.max(vals) - np.min(vals)


def ref_std_pop(vals):
    """Population standard deviation (ddof=0)."""
    return np.std(vals, ddof=0)


def ref_std_r(vals):
    """Sample standard deviation with Bessel's correction (ddof=1)."""
    return np.std(vals, ddof=1)


def ref_covariance(vals1, vals2, mean1, mean2, lag=0):
    """Covariance matching the Java AccStats implementation (n+1-lag divisor)."""
    lag = abs(lag)
    n = len(vals1)
    cov = 0.0
    for i in range(lag, n):
        cov += (vals1[i] - mean1) * (vals2[i] - mean2)
    cov /= (n + 1 - lag)
    return cov


def ref_correlation(vals1, vals2, lag=0):
    """Pearson correlation matching the Java AccStats implementation."""
    lag = abs(lag)
    nmax = len(vals1)
    n = nmax - lag
    if n <= 0:
        return float('nan')

    sx = sy = sxx = syy = sxy = 0.0
    for i in range(lag, nmax):
        x = vals1[i - lag]
        y = vals2[i]
        sx += x
        sy += y
        sxx += x * x
        syy += y * y
        sxy += x * y

    cov = sxy / n - sx * sy / n / n
    sigmax = np.sqrt(max(0, sxx / n - sx * sx / n / n))
    sigmay = np.sqrt(max(0, syy / n - sy * sy / n / n))

    if sigmax == 0 or sigmay == 0:
        return float('nan')
    return cov / sigmax / sigmay


def ref_percentiles_r7(vals, percentile_points):
    """R-style Type 7 quantile interpolation."""
    sorted_vals = np.sort(vals)
    n = len(sorted_vals)
    results = []
    for p in percentile_points:
        h = p * (n - 1) + 1
        if h <= 1.0:
            results.append(sorted_vals[0])
        elif h >= n:
            results.append(sorted_vals[-1])
        else:
            hfloor = int(np.floor(h))
            xh = sorted_vals[hfloor - 1]
            xh2 = sorted_vals[hfloor]
            results.append(xh + (h - hfloor) * (xh2 - xh))
    return results


def ref_angle_avg_std(vals1, vals2):
    """atan2-based angle avg and std with Bessel's correction."""
    angles = np.arctan2(vals1, vals2)
    avg = np.mean(angles)
    std = np.std(angles, ddof=1)
    return avg, std


def ref_gravity_ema(x, y, z, sample_rate, weight=0.9):
    """Exponential moving average gravity estimation."""
    n = len(x)
    gn = n - (sample_rate - 1)
    g_start = n - gn

    gx = np.zeros(gn)
    gy = np.zeros(gn)
    gz = np.zeros(gn)

    x_mov = (1 - weight) * x[0]
    y_mov = (1 - weight) * y[0]
    z_mov = (1 - weight) * z[0]

    for i in range(1, n):
        x_mov = x_mov * weight + (1 - weight) * x[i]
        y_mov = y_mov * weight + (1 - weight) * y[i]
        z_mov = z_mov * weight + (1 - weight) * z[i]
        if i >= g_start:
            gx[i - g_start] = x_mov
            gy[i - g_start] = y_mov
            gz[i - g_start] = z_mov

    return np.mean(gx), np.mean(gy), np.mean(gz)


def ref_vm(x, y, z):
    """Vector magnitude."""
    return np.sqrt(x ** 2 + y ** 2 + z ** 2)


def ref_butterworth_filter(signal, fc=20, fs=100, order=4):
    """Reference 4th-order Butterworth low-pass filter using scipy."""
    from scipy.signal import butter, lfilter
    b, a = butter(order, fc, 'low', fs=fs)
    return lfilter(b, a, signal)


def ref_median_sliding_window(nums, k):
    """Sliding window median matching Java implementation."""
    n = len(nums)
    result = np.zeros(n - k + 1)
    for i in range(n - k + 1):
        window = np.sort(nums[i:i + k])
        if k % 2 == 0:
            result[i] = (window[k // 2 - 1] + window[k // 2]) / 2.0
        else:
            result[i] = window[k // 2]
    return result


def ref_spectral_features(v, sample_rate):
    """Reference spectral features with Hann windowing and DFT."""
    n = len(v)
    v_mean = np.mean(v)

    # Apply Hann window before DFT
    hann = 0.5 * (1 - np.cos(2 * np.pi * np.arange(n) / (n - 1)))
    windowed = (v - v_mean) * hann

    # DFT power spectrum (one-sided, normalized by N^2)
    fft_result = np.fft.rfft(windowed)
    power = np.abs(fft_result) ** 2 / (n * n)

    num_bins = len(power)  # n/2 + 1

    # Dominant frequency (skip DC bin at index 0)
    freq_res = float(sample_rate) / n
    k_max = np.argmax(power[1:]) + 1
    fmax = k_max * freq_res
    pmax = np.log(power[k_max] + 1e-8)

    # Spectral entropy (normalized)
    power_no_dc = power[1:]
    total_power = np.sum(power_no_dc)
    entropy = 0.0
    for p_val in power_no_dc:
        p_norm = p_val / (total_power + 1e-8)
        if p_norm > 0:
            entropy += -p_norm * np.log(p_norm + 1e-8)
    entropy /= np.log(len(power_no_dc))

    return fmax, pmax, entropy


def compute_reference(x, y, z, sample_rate=100):
    """Compute all 44 reference features using correct algorithms."""
    n = len(x)
    N = float(n)

    # --- ENMO with Butterworth low-pass filter ---
    vm = ref_vm(x, y, z)
    enmo = vm - 1.0
    filtered_enmo = ref_butterworth_filter(enmo, fc=20, fs=sample_rate, order=4)
    enmo_trunc = np.maximum(filtered_enmo, 0.0)
    enmo_abs = np.abs(filtered_enmo)

    # --- Basic statistics (from raw axes) ---
    x_mean = ref_mean(x)
    y_mean = ref_mean(y)
    z_mean = ref_mean(z)
    x_range = ref_range(x)
    y_range = ref_range(y)
    z_range = ref_range(z)
    x_std = ref_std_pop(x)
    y_std = ref_std_pop(y)
    z_std = ref_std_pop(z)
    xy_cov = ref_covariance(x, y, x_mean, y_mean)
    xz_cov = ref_covariance(x, z, x_mean, z_mean)
    yz_cov = ref_covariance(y, z, y_mean, z_mean)

    # --- San Diego features ---

    # Gravity estimation (EMA with correct weight=0.9)
    gx, gy, gz = ref_gravity_ema(x, y, z, sample_rate, weight=0.9)

    # Gravity-subtracted signals
    wx = x - gx
    wy = y - gy
    wz = z - gz
    v = ref_vm(wx, wy, wz)

    sd_mean = ref_mean(v)
    sd_std = ref_std_r(v)
    sd_cv = sd_std / sd_mean if sd_mean != 0 else 0.0

    # R7 percentiles of gravity-subtracted VM
    pcts = ref_percentiles_r7(v, [0, 0.25, 0.5, 0.75, 1])

    # Correlations
    auto_corr = ref_correlation(v, v, sample_rate)
    if not np.isfinite(auto_corr):
        auto_corr = 0.0
    xy_corr = ref_correlation(wx, wy, 0)
    if not np.isfinite(xy_corr):
        xy_corr = 0.0
    xz_corr = ref_correlation(wx, wz, 0)
    if not np.isfinite(xz_corr):
        xz_corr = 0.0
    yz_corr = ref_correlation(wy, wz, 0)
    if not np.isfinite(yz_corr):
        yz_corr = 0.0

    # Angles
    roll_avg, roll_std = ref_angle_avg_std(wy, wz)
    pitch_avg, pitch_std = ref_angle_avg_std(wz, wx)
    yaw_avg, yaw_std = ref_angle_avg_std(wy, wx)

    # Gravity angles
    gxy_angle = np.arctan2(gy, gz)
    gzx_angle = np.arctan2(gz, gx)
    gyx_angle = np.arctan2(gy, gx)

    # --- MAD features ---
    unfiltered_vm = ref_vm(x, y, z) - 1.0
    vm_mean = ref_mean(unfiltered_vm)
    vm_std = ref_std_pop(unfiltered_vm)

    diff = unfiltered_vm - vm_mean
    MAD = np.sum(np.abs(diff)) / N
    MPD = np.sum(np.power(np.abs(diff), 1.5)) / np.power(N, 1.5)

    norm_diff = diff / (vm_std + 1e-8)
    skew_sum = np.sum(norm_diff ** 3)
    skew = skew_sum * N / ((N - 1) * (N - 2))

    kurt_sum = np.sum(norm_diff ** 4)
    kurt = (kurt_sum * N * (N + 1) / ((N - 1) * (N - 2) * (N - 3) * (N - 4))
            - 3 * (N - 1) ** 2 / ((N - 2) * (N - 3)))

    # --- Arm features ---
    k = 5 * sample_rate  # 500
    rmx = ref_median_sliding_window(x, k)
    rmy = ref_median_sliding_window(y, k)
    rmz = ref_median_sliding_window(z, k)

    angel_z = np.arctan(rmz / (rmx ** 2 + rmy ** 2)) * 180.0 / np.pi

    # 5-sec averages
    block_size = 5 * sample_rate
    n_avgs = int(np.ceil(len(angel_z) / float(block_size)))
    avgs = np.zeros(n_avgs)
    count = 0
    total = 0.0
    j = 0
    for i in range(len(angel_z)):
        count += 1
        total += angel_z[i]
        if count == block_size or i == len(angel_z) - 1:
            avgs[j] = total / count
            j += 1
            total = 0.0
            count = 0

    avg_arm_angel = ref_mean(avgs[:j])

    # Absolute difference
    if j > 1:
        abs_diff = np.abs(np.diff(avgs[:j]))
        avg_arm_angel_abs_diff = ref_mean(abs_diff)
    else:
        avg_arm_angel_abs_diff = 0.0

    # --- Spectral features ---
    fmax, pmax, entropy = ref_spectral_features(v, sample_rate)

    return {
        'enmoTrunc': ref_mean(enmo_trunc),
        'enmoAbs': ref_mean(enmo_abs),
        'xMean': x_mean,
        'yMean': y_mean,
        'zMean': z_mean,
        'xRange': x_range,
        'yRange': y_range,
        'zRange': z_range,
        'xStd': x_std,
        'yStd': y_std,
        'zStd': z_std,
        'xyCov': xy_cov,
        'xzCov': xz_cov,
        'yzCov': yz_cov,
        'mean': sd_mean,
        'sd': sd_std,
        'coefvariation': sd_cv,
        'median': pcts[2],
        'min': pcts[0],
        'max': pcts[4],
        '25thp': pcts[1],
        '75thp': pcts[3],
        'autocorr': auto_corr,
        'corrxy': xy_corr,
        'corrxz': xz_corr,
        'corryz': yz_corr,
        'avgroll': roll_avg,
        'avgpitch': pitch_avg,
        'avgyaw': yaw_avg,
        'sdroll': roll_std,
        'sdpitch': pitch_std,
        'sdyaw': yaw_std,
        'rollg': gxy_angle,
        'pitchg': gzx_angle,
        'yawg': gyx_angle,
        'MAD': MAD,
        'MPD': MPD,
        'skew': skew,
        'kurt': kurt,
        'avgArmAngel': avg_arm_angel,
        'avgArmAngelAbsDiff': avg_arm_angel_abs_diff,
        'fmax': fmax,
        'pmax': pmax,
        'entropy': entropy,
    }


ALL_FEATURES = [
    'enmoTrunc', 'enmoAbs',
    'xMean', 'yMean', 'zMean',
    'xRange', 'yRange', 'zRange',
    'xStd', 'yStd', 'zStd',
    'xyCov', 'xzCov', 'yzCov',
    'mean', 'sd', 'coefvariation',
    'median', 'min', 'max', '25thp', '75thp',
    'autocorr', 'corrxy', 'corrxz', 'corryz',
    'avgroll', 'avgpitch', 'avgyaw',
    'sdroll', 'sdpitch', 'sdyaw',
    'rollg', 'pitchg', 'yawg',
    'MAD', 'MPD', 'skew', 'kurt',
    'avgArmAngel', 'avgArmAngelAbsDiff',
    'fmax', 'pmax', 'entropy',
]


# ============================================================
# Test infrastructure
# ============================================================

def assert_close(actual, expected, name="", rtol=1e-4, atol=1e-6):
    """Assert that actual is close to expected within combined tolerance."""
    err = abs(actual - expected)
    tol = atol + rtol * abs(expected)
    assert err <= tol, (
        f"{name}: actual={actual:.12g}, expected={expected:.12g}, "
        f"err={err:.6g}, tol={tol:.6g}"
    )


@pytest.fixture(scope="session")
def setup_pipeline():
    """Generate raw sensor data with calibration errors and run pipeline."""
    x_raw, y_raw, z_raw, x_ideal, y_ideal, z_ideal = generate_test_data()
    input_csv = '/app/data/input.csv'
    save_csv(x_raw, y_raw, z_raw, input_csv)

    # Run pipeline via make
    r = subprocess.run(
        ['make', '-C', '/app', 'pipeline'],
        capture_output=True, text=True, timeout=180
    )
    assert r.returncode == 0, (
        f"Pipeline failed (make -C /app pipeline):\n"
        f"STDOUT: {r.stdout}\nSTDERR: {r.stderr}"
    )

    return x_ideal, y_ideal, z_ideal


@pytest.fixture(scope="session")
def java_output(setup_pipeline):
    """Load the Java pipeline output."""
    output_json = '/app/output/features.json'
    assert os.path.exists(output_json), f"Pipeline did not create {output_json}"
    with open(output_json) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def reference_output(setup_pipeline):
    """Compute reference features from ideal (correctly calibrated) data."""
    x_ideal, y_ideal, z_ideal = setup_pipeline
    return compute_reference(x_ideal, y_ideal, z_ideal, SAMPLE_RATE)


@pytest.mark.parametrize("feature", ALL_FEATURES)
def test_feature(java_output, reference_output, feature):
    """Validate each feature against the Python reference."""
    assert feature in java_output, f"Feature '{feature}' not found in Java output"
    assert feature in reference_output, f"Feature '{feature}' not found in reference"
    assert_close(java_output[feature], reference_output[feature], feature)
