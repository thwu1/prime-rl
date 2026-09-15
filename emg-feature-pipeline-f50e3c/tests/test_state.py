"""EMG pipeline verification tests.

"""
import pytest
import numpy as np
import json
import subprocess
import os
import math
from scipy.signal import butter, iirnotch, filtfilt


# ============================================================
# Reference implementations
# ============================================================

def ref_filter_bandpass_notch(data, fs):
    """Apply reference bandpass + notch filters."""
    filtered = data.copy()
    b, a = butter(4, [20 / (fs / 2), 450 / (fs / 2)], btype="bandpass")
    filtered = filtfilt(b, a, filtered, axis=0)
    b, a = iirnotch(60, 60 / 3, fs)
    filtered = filtfilt(b, a, filtered, axis=0)
    return filtered


def ref_filter_highpass(data, fs, cutoff, order):
    """Apply reference highpass filter."""
    filtered = data.copy()
    b, a = butter(order, cutoff / (fs / 2), btype="highpass")
    filtered = filtfilt(b, a, filtered, axis=0)
    return filtered


def ref_window(data, ws, wi):
    n = data.shape[0]
    c = data.shape[1]
    nw = (n - ws) // wi + 1
    windows = np.zeros((nw, c, ws))
    for i in range(nw):
        windows[i] = data[i * wi : i * wi + ws].T
    return windows


def ref_mav(w):
    return np.mean(np.abs(w), axis=2)


def ref_zc(w):
    sc = np.diff(np.sign(w), axis=2)
    return np.sum(sc == -2, axis=2) + np.sum(sc == 2, axis=2)


def ref_ssc(w):
    w2 = w[:, :, 2:]
    w1 = w[:, :, 1:-1]
    w0 = w[:, :, :-2]
    return np.sum(((w1 - w0) * (w1 - w2)) >= 0.0, axis=2)


def ref_wl(w):
    return np.sum(np.abs(np.diff(w, axis=2)), axis=2)


def _efp(windows):
    return np.log(windows ** 2 + np.spacing(1))


def _tdpsd_combine(ebp, efp):
    num = -2 * efp * ebp
    den = efp ** 2 + ebp ** 2
    return num / den


def _tdpsd_moments(w):
    m0 = np.sqrt(np.sum(w ** 2, axis=2)) / (w.shape[2] - 1)
    m0 = m0 ** 0.1 / 0.1
    d1 = np.diff(w, n=1, axis=2)
    m2 = np.sqrt(np.sum(d1 ** 2, axis=2) / (w.shape[2] - 1))
    m2 = m2 ** 0.1 / 0.1
    d2 = np.diff(d1, n=1, axis=2)
    m4 = np.sqrt(np.sum(d2 ** 2, axis=2) / (w.shape[2] - 1))
    m4 = m4 ** 0.1 / 0.1
    return m0, m2, m4


def ref_m0(windows):
    def closure(w):
        m0 = np.sqrt(np.sum(w ** 2, axis=2)) / (w.shape[2] - 1)
        m0 = m0 ** 0.1 / 0.1
        return np.log(np.abs(m0))
    ebp = closure(windows)
    efp = closure(_efp(windows))
    return _tdpsd_combine(ebp, efp)


def ref_m2(windows):
    def closure(w):
        m0 = np.sqrt(np.sum(w ** 2, axis=2)) / (w.shape[2] - 1)
        m0 = m0 ** 0.1 / 0.1
        d1 = np.diff(w, n=1, axis=2)
        m2 = np.sqrt(np.sum(d1 ** 2, axis=2) / (w.shape[2] - 1))
        m2 = m2 ** 0.1 / 0.1
        return np.log(np.abs(m0 - m2))
    ebp = closure(windows)
    efp = closure(_efp(windows))
    return _tdpsd_combine(ebp, efp)


def ref_m4(windows):
    def closure(w):
        m0 = np.sqrt(np.sum(w ** 2, axis=2)) / (w.shape[2] - 1)
        m0 = m0 ** 0.1 / 0.1
        d1 = np.diff(w, n=1, axis=2)
        d2 = np.diff(d1, n=1, axis=2)
        m4 = np.sqrt(np.sum(d2 ** 2, axis=2) / (w.shape[2] - 1))
        m4 = m4 ** 0.1 / 0.1
        return np.log(np.abs(m0 - m4))
    ebp = closure(windows)
    efp = closure(_efp(windows))
    return _tdpsd_combine(ebp, efp)


def ref_sparsi(windows):
    def closure(w):
        m0, m2, m4 = _tdpsd_moments(w)
        sparsi = np.sqrt(np.abs((m0 - m2) * (m0 - m4))) / m0
        return np.log(np.abs(sparsi))
    ebp = closure(windows)
    efp = closure(_efp(windows))
    return _tdpsd_combine(ebp, efp)


def ref_irf(windows):
    def closure(w):
        m0, m2, m4 = _tdpsd_moments(w)
        irf = m2 / np.sqrt(m0 * m4)
        return np.log(np.abs(irf))
    ebp = closure(windows)
    efp = closure(_efp(windows))
    return _tdpsd_combine(ebp, efp)


def ref_wlf(windows):
    def closure(w):
        d1 = np.diff(w, n=1, axis=2)
        d2 = np.diff(d1, n=1, axis=2)
        wlf = np.sqrt(np.sum(np.abs(d1), axis=2) / np.sum(np.abs(d2), axis=2))
        return np.log(np.abs(wlf))
    ebp = closure(windows)
    efp = closure(_efp(windows))
    return _tdpsd_combine(ebp, efp)


def ref_act(w):
    return np.mean(w ** 2, axis=2)


def ref_mob(w):
    m0 = np.mean(w ** 2, axis=2)
    m2 = np.sum(np.diff(w, axis=2) ** 2, axis=2) / w.shape[2]
    return np.sqrt(m2 / m0)


def ref_comp(w):
    m2 = np.sum(np.diff(w, axis=2) ** 2, axis=2) / w.shape[2]
    m4 = np.sum(np.diff(np.diff(w, axis=2), axis=2) ** 2, axis=2) / w.shape[2]
    return np.sqrt(m4 / m2)


def ref_mdf(w, fs):
    nfft = 2 ** math.ceil(math.log2(w.shape[2]))
    spec = np.fft.fft(w, n=nfft, axis=2) / w.shape[2]
    spec = spec[:, :, : nfft // 2]
    POW = np.real(spec * np.conj(spec))
    totalPOW = np.sum(POW, axis=2)
    cumPOW = np.cumsum(POW, axis=2)
    mf = np.zeros((w.shape[0], w.shape[1]))
    for i in range(w.shape[0]):
        for j in range(w.shape[1]):
            idx = np.argwhere(cumPOW[i, j, :] > totalPOW[i, j] / 2)[0][0]
            mf[i, j] = (fs / 2) * idx / (nfft / 2)
    return mf


def ref_mnf(w, fs):
    nfft = 2 ** math.ceil(math.log2(w.shape[2]))
    spec = np.fft.fft(w, n=nfft, axis=2) / w.shape[2]
    f = np.fft.fftfreq(nfft) * fs
    spec = spec[:, :, : nfft // 2]
    f = f[: nfft // 2]
    f_broadcast = np.broadcast_to(f, spec.shape)
    POW = spec * np.conj(spec)
    return np.real(np.sum(POW * f_broadcast, axis=2) / np.sum(POW, axis=2))


def ref_sampen(windows, dim=2, tolerance=0.3):
    N = windows.shape[2]
    wmean = np.mean(windows, axis=2, keepdims=True)
    wstd = np.std(windows, axis=2, keepdims=True)
    series = (windows - wmean) / wstd
    sampen = np.zeros((windows.shape[0], windows.shape[1]))
    for wi in range(windows.shape[0]):
        for ch in range(windows.shape[1]):
            results = []
            for j in [1, 2]:
                m = dim + j - 1
                patterns = np.zeros((m, N - m + 1))
                count = np.zeros(N - m)
                for k in range(m):
                    patterns[k, :] = series[wi, ch, k : N - m + k + 1]
                for k in range(N - m):
                    dist = np.max(
                        np.abs(patterns - patterns[:, k : k + 1]), axis=0
                    )
                    mask = dist <= tolerance
                    count[k] = np.sum(mask) - 1
                count = count / (N - dim - 1)
                results.append(np.mean(count))
            sampen[wi, ch] = np.log(
                (results[0] + np.spacing(1)) / (results[1] + np.spacing(1))
            )
    return sampen


def ref_fuzzyen(windows, dim=2, tolerance=0.3, win=2):
    r = tolerance * np.std(windows, axis=2)
    N = windows.shape[2]
    fuzzyen = np.zeros((windows.shape[0], windows.shape[1]))
    for w_idx in range(windows.shape[0]):
        for ch in range(windows.shape[1]):
            results = []
            for j in [1, 2]:
                m = dim + j - 1
                dataMat = np.zeros((m, N - m + 1))
                phi = np.zeros(N - m + 1)
                for k in range(m):
                    dataMat[k, :] = windows[w_idx, ch, k : N - m + k + 1]
                # subtract local mean from each pattern
                for k in range(N - m + 1):
                    dataMat[:, k] -= np.mean(dataMat[:, k])
                for k in range(N - m):
                    tmp = np.max(
                        np.abs(dataMat - dataMat[:, k : k + 1]), axis=0
                    )
                    simi = np.exp((-1) * (tmp ** win) / r[w_idx, ch])
                    phi[k] = (np.sum(simi) - 1) / (N - m - 1)
                results.append(np.sum(phi) / (N - m))
            fuzzyen[w_idx, ch] = np.log(
                (results[0] + np.spacing(1)) / (results[1] + np.spacing(1))
            )
    return fuzzyen


# ============================================================
# Fixture 1: Full pipeline (4-channel, all features, with metrics)
# ============================================================

@pytest.fixture(scope="module")
def pipeline_output(tmp_path_factory):
    tmpdir = str(tmp_path_factory.mktemp("emg"))

    # Generate synthetic EMG data
    np.random.seed(42)
    n_samples = 1000
    n_ch = 4
    fs = 1000.0
    t = np.arange(n_samples) / fs

    data = np.column_stack(
        [
            0.5 * np.sin(2 * np.pi * 50 * t)
            + 0.3 * np.sin(2 * np.pi * 150 * t)
            + 0.1 * np.random.randn(n_samples),
            0.4 * np.sin(2 * np.pi * 80 * t)
            + 0.2 * np.sin(2 * np.pi * 200 * t)
            + 0.1 * np.random.randn(n_samples),
            0.6 * np.sin(2 * np.pi * 30 * t)
            + 0.15 * np.random.randn(n_samples),
            0.3 * np.sin(2 * np.pi * 120 * t)
            + 0.25 * np.sin(2 * np.pi * 250 * t)
            + 0.1 * np.random.randn(n_samples),
        ]
    )

    input_path = os.path.join(tmpdir, "emg.csv")
    np.savetxt(input_path, data, delimiter=",")

    # Labels and predictions for metrics
    labels = np.array([0, 0, 0, 1, 1, 1, 2, 2])
    preds = np.array([0, 0, 1, 1, 1, 2, 2, -1])
    labels_path = os.path.join(tmpdir, "labels.csv")
    preds_path = os.path.join(tmpdir, "preds.csv")
    np.savetxt(labels_path, labels, fmt="%d")
    np.savetxt(preds_path, preds, fmt="%d")

    config = {
        "sampling_frequency": fs,
        "window_size": 100,
        "window_increment": 50,
        "filters": [
            {"name": "bandpass", "cutoff": [20, 450], "order": 4},
            {"name": "notch", "cutoff": 60, "bandwidth": 3},
        ],
        "features": ["HTD", "TDPSD", "HJORTH", "SAMPEN", "FUZZYEN", "MDF", "MNF"],
        "labels_file": labels_path,
        "predictions_file": preds_path,
        "null_label": 0,
    }
    config_path = os.path.join(tmpdir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f)

    output_dir = os.path.join(tmpdir, "output")
    os.makedirs(output_dir)

    result = subprocess.run(
        [
            "python3",
            "/app/emg_pipeline.py",
            "--input",
            input_path,
            "--config",
            config_path,
            "--output",
            output_dir,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    # Reference: filter and window
    filtered = ref_filter_bandpass_notch(data, fs)
    windows = ref_window(filtered, 100, 50)

    features = {}
    summary = {}
    metrics = {}
    if result.returncode == 0:
        feat_path = os.path.join(output_dir, "features.json")
        if os.path.exists(feat_path):
            with open(feat_path) as f:
                features = json.load(f)
        sum_path = os.path.join(output_dir, "summary.json")
        if os.path.exists(sum_path):
            with open(sum_path) as f:
                summary = json.load(f)
        met_path = os.path.join(output_dir, "metrics.json")
        if os.path.exists(met_path):
            with open(met_path) as f:
                metrics = json.load(f)

    return {
        "rc": result.returncode,
        "stderr": result.stderr,
        "stdout": result.stdout,
        "features": features,
        "summary": summary,
        "metrics": metrics,
        "ref_windows": windows,
        "output_dir": output_dir,
        "fs": fs,
    }


# ============================================================
# Fixture 2: Minimal config (single-channel, HTD only, no filters, no metrics)
# ============================================================

@pytest.fixture(scope="module")
def minimal_output(tmp_path_factory):
    tmpdir = str(tmp_path_factory.mktemp("minimal"))

    np.random.seed(123)
    data = np.random.randn(500, 1)
    input_path = os.path.join(tmpdir, "emg.csv")
    np.savetxt(input_path, data, delimiter=",")

    config = {
        "sampling_frequency": 500.0,
        "window_size": 50,
        "window_increment": 25,
        "features": ["HTD"],
    }
    config_path = os.path.join(tmpdir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f)

    output_dir = os.path.join(tmpdir, "output")
    os.makedirs(output_dir)

    result = subprocess.run(
        [
            "python3",
            "/app/emg_pipeline.py",
            "--input",
            input_path,
            "--config",
            config_path,
            "--output",
            output_dir,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    features = {}
    summary = {}
    if result.returncode == 0:
        feat_path = os.path.join(output_dir, "features.json")
        if os.path.exists(feat_path):
            with open(feat_path) as f:
                features = json.load(f)
        sum_path = os.path.join(output_dir, "summary.json")
        if os.path.exists(sum_path):
            with open(sum_path) as f:
                summary = json.load(f)

    windows = ref_window(data, 50, 25)

    return {
        "rc": result.returncode,
        "stderr": result.stderr,
        "features": features,
        "summary": summary,
        "ref_windows": windows,
        "output_dir": output_dir,
    }


# ============================================================
# Fixture 3: TDPSD + duplicate M0 (2-channel, deduplication test)
# ============================================================

@pytest.fixture(scope="module")
def tdpsd_output(tmp_path_factory):
    tmpdir = str(tmp_path_factory.mktemp("tdpsd"))

    np.random.seed(999)
    data = np.random.randn(300, 2) * 0.5
    input_path = os.path.join(tmpdir, "emg.csv")
    np.savetxt(input_path, data, delimiter=",")

    config = {
        "sampling_frequency": 1000.0,
        "window_size": 64,
        "window_increment": 32,
        "features": ["TDPSD", "M0"],
    }
    config_path = os.path.join(tmpdir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f)

    output_dir = os.path.join(tmpdir, "output")
    os.makedirs(output_dir)

    result = subprocess.run(
        [
            "python3",
            "/app/emg_pipeline.py",
            "--input",
            input_path,
            "--config",
            config_path,
            "--output",
            output_dir,
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )

    features = {}
    summary = {}
    if result.returncode == 0:
        feat_path = os.path.join(output_dir, "features.json")
        if os.path.exists(feat_path):
            with open(feat_path) as f:
                features = json.load(f)
        sum_path = os.path.join(output_dir, "summary.json")
        if os.path.exists(sum_path):
            with open(sum_path) as f:
                summary = json.load(f)

    windows = ref_window(data, 64, 32)

    return {
        "rc": result.returncode,
        "stderr": result.stderr,
        "features": features,
        "summary": summary,
        "ref_windows": windows,
    }


# ============================================================
# Fixture 4: Highpass filter + HTD + FUZZYEN (3-channel)
# ============================================================

@pytest.fixture(scope="module")
def highpass_output(tmp_path_factory):
    tmpdir = str(tmp_path_factory.mktemp("highpass"))

    np.random.seed(7777)
    n_samples = 600
    n_ch = 3
    fs = 2000.0
    t = np.arange(n_samples) / fs

    data = np.column_stack(
        [
            0.3 * np.sin(2 * np.pi * 5 * t)
            + 0.4 * np.sin(2 * np.pi * 100 * t)
            + 0.08 * np.random.randn(n_samples),
            0.5 * np.sin(2 * np.pi * 10 * t)
            + 0.2 * np.sin(2 * np.pi * 250 * t)
            + 0.06 * np.random.randn(n_samples),
            0.2 * np.sin(2 * np.pi * 3 * t)
            + 0.35 * np.sin(2 * np.pi * 180 * t)
            + 0.1 * np.random.randn(n_samples),
        ]
    )

    input_path = os.path.join(tmpdir, "emg.csv")
    np.savetxt(input_path, data, delimiter=",")

    config = {
        "sampling_frequency": fs,
        "window_size": 128,
        "window_increment": 64,
        "filters": [
            {"name": "highpass", "cutoff": 20, "order": 2},
        ],
        "features": ["HTD", "FUZZYEN"],
    }
    config_path = os.path.join(tmpdir, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f)

    output_dir = os.path.join(tmpdir, "output")
    os.makedirs(output_dir)

    result = subprocess.run(
        [
            "python3",
            "/app/emg_pipeline.py",
            "--input",
            input_path,
            "--config",
            config_path,
            "--output",
            output_dir,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    # Reference: highpass filter
    filtered = ref_filter_highpass(data, fs, 20, 2)
    windows = ref_window(filtered, 128, 64)

    features = {}
    summary = {}
    if result.returncode == 0:
        feat_path = os.path.join(output_dir, "features.json")
        if os.path.exists(feat_path):
            with open(feat_path) as f:
                features = json.load(f)
        sum_path = os.path.join(output_dir, "summary.json")
        if os.path.exists(sum_path):
            with open(sum_path) as f:
                summary = json.load(f)

    return {
        "rc": result.returncode,
        "stderr": result.stderr,
        "features": features,
        "summary": summary,
        "ref_windows": windows,
        "output_dir": output_dir,
        "fs": fs,
    }


# ============================================================
# Tests: Full pipeline execution
# ============================================================

def test_pipeline_runs(pipeline_output):
    assert pipeline_output["rc"] == 0, (
        f"Pipeline failed with code {pipeline_output['rc']}.\n"
        f"stderr: {pipeline_output['stderr']}"
    )


def test_output_features_file(pipeline_output):
    assert os.path.exists(
        os.path.join(pipeline_output["output_dir"], "features.json")
    )


def test_output_summary_file(pipeline_output):
    assert os.path.exists(
        os.path.join(pipeline_output["output_dir"], "summary.json")
    )


def test_output_metrics_file(pipeline_output):
    assert os.path.exists(
        os.path.join(pipeline_output["output_dir"], "metrics.json")
    )


def test_summary_content(pipeline_output):
    s = pipeline_output["summary"]
    assert s["num_windows"] == 19
    assert s["num_channels"] == 4
    assert s["sampling_frequency"] == 1000.0
    feats = s["features_extracted"]
    assert "MAV" in feats
    assert "M0" in feats
    assert "ACT" in feats
    assert "SAMPEN" in feats
    assert "FUZZYEN" in feats
    assert "MDF" in feats
    # 4 HTD + 6 TDPSD + 3 HJORTH + SAMPEN + FUZZYEN + MDF + MNF = 17
    assert len(feats) == 17


# ============================================================
# Tests: HTD features
# ============================================================

def test_htd_mav(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_mav(w)
    actual = np.array(pipeline_output["features"]["MAV"])
    np.testing.assert_allclose(actual, expected, rtol=1e-6)


def test_htd_zc(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_zc(w)
    actual = np.array(pipeline_output["features"]["ZC"])
    np.testing.assert_allclose(actual, expected, atol=0.5)


def test_htd_ssc(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_ssc(w)
    actual = np.array(pipeline_output["features"]["SSC"])
    np.testing.assert_allclose(actual, expected, atol=0.5)


def test_htd_wl(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_wl(w)
    actual = np.array(pipeline_output["features"]["WL"])
    np.testing.assert_allclose(actual, expected, rtol=1e-6)


# ============================================================
# Tests: TDPSD features
# ============================================================

def test_tdpsd_m0(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_m0(w)
    actual = np.array(pipeline_output["features"]["M0"])
    assert np.all(np.abs(actual) <= 1.0 + 1e-10), "M0 out of [-1,1]"
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


def test_tdpsd_m2(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_m2(w)
    actual = np.array(pipeline_output["features"]["M2"])
    assert np.all(np.abs(actual) <= 1.0 + 1e-10), "M2 out of [-1,1]"
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


def test_tdpsd_m4(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_m4(w)
    actual = np.array(pipeline_output["features"]["M4"])
    assert np.all(np.abs(actual) <= 1.0 + 1e-10), "M4 out of [-1,1]"
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


def test_tdpsd_sparsi(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_sparsi(w)
    actual = np.array(pipeline_output["features"]["SPARSI"])
    assert np.all(np.abs(actual) <= 1.0 + 1e-10), "SPARSI out of [-1,1]"
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


def test_tdpsd_irf(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_irf(w)
    actual = np.array(pipeline_output["features"]["IRF"])
    assert np.all(np.abs(actual) <= 1.0 + 1e-10), "IRF out of [-1,1]"
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


def test_tdpsd_wlf(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_wlf(w)
    actual = np.array(pipeline_output["features"]["WLF"])
    assert np.all(np.abs(actual) <= 1.0 + 1e-10), "WLF out of [-1,1]"
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


# ============================================================
# Tests: Hjorth parameters
# ============================================================

def test_hjorth_act(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_act(w)
    actual = np.array(pipeline_output["features"]["ACT"])
    np.testing.assert_allclose(actual, expected, rtol=1e-6)


def test_hjorth_mob(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_mob(w)
    actual = np.array(pipeline_output["features"]["MOB"])
    np.testing.assert_allclose(actual, expected, rtol=1e-6)


def test_hjorth_comp(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_comp(w)
    actual = np.array(pipeline_output["features"]["COMP"])
    np.testing.assert_allclose(actual, expected, rtol=1e-6)


# ============================================================
# Tests: Frequency features
# ============================================================

def test_mdf(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_mdf(w, pipeline_output["fs"])
    actual = np.array(pipeline_output["features"]["MDF"])
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


def test_mnf(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_mnf(w, pipeline_output["fs"])
    actual = np.array(pipeline_output["features"]["MNF"])
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


# ============================================================
# Tests: SAMPEN
# ============================================================

def test_sampen_shape(pipeline_output):
    sampen = np.array(pipeline_output["features"]["SAMPEN"])
    assert sampen.shape == (19, 4), f"Expected (19,4), got {sampen.shape}"


def test_sampen_finite(pipeline_output):
    sampen = np.array(pipeline_output["features"]["SAMPEN"])
    assert np.all(np.isfinite(sampen)), "SAMPEN contains non-finite values"


def test_sampen_values(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_sampen(w)
    actual = np.array(pipeline_output["features"]["SAMPEN"])
    np.testing.assert_allclose(actual, expected, rtol=1e-4)


# ============================================================
# Tests: FUZZYEN (full pipeline)
# ============================================================

def test_fuzzyen_shape(pipeline_output):
    fe = np.array(pipeline_output["features"]["FUZZYEN"])
    assert fe.shape == (19, 4), f"Expected (19,4), got {fe.shape}"


def test_fuzzyen_finite(pipeline_output):
    fe = np.array(pipeline_output["features"]["FUZZYEN"])
    assert np.all(np.isfinite(fe)), "FUZZYEN contains non-finite values"


def test_fuzzyen_values(pipeline_output):
    w = pipeline_output["ref_windows"]
    expected = ref_fuzzyen(w)
    actual = np.array(pipeline_output["features"]["FUZZYEN"])
    np.testing.assert_allclose(actual, expected, rtol=1e-4)


# ============================================================
# Tests: Classification metrics
# ============================================================

def test_metrics_ca(pipeline_output):
    m = pipeline_output["metrics"]
    # After removing rejection at index 7: y_true=[0,0,0,1,1,1,2] y_pred=[0,0,1,1,1,2,2]
    # Correct: 5/7
    assert abs(m["CA"] - 5.0 / 7.0) < 1e-6


def test_metrics_aer(pipeline_output):
    m = pipeline_output["metrics"]
    # Remove predictions==0 (indices 0,1): y_true=[0,1,1,1,2] y_pred=[1,1,1,2,2]
    # Correct: 3/5 => AER = 1 - 3/5 = 0.4
    assert abs(m["AER"] - 0.4) < 1e-6


def test_metrics_ins(pipeline_output):
    m = pipeline_output["metrics"]
    # true transitions: 2, pred transitions: 2 => INS = max(0, 0/7) = 0
    assert abs(m["INS"] - 0.0) < 1e-6


def test_metrics_rej_rate(pipeline_output):
    m = pipeline_output["metrics"]
    # 1 rejection out of 8 original predictions
    assert abs(m["REJ_RATE"] - 0.125) < 1e-6


def test_metrics_f1(pipeline_output):
    m = pipeline_output["metrics"]
    # Weighted F1 = 76/105 ≈ 0.72381
    assert abs(m["F1"] - 76.0 / 105.0) < 1e-4


def test_metrics_conf_mat(pipeline_output):
    m = pipeline_output["metrics"]
    expected = [[2, 1, 0], [0, 2, 1], [0, 0, 1]]
    assert m["CONF_MAT"] == expected


# ============================================================
# Tests: Minimal config (single-channel, HTD only, no filters)
# ============================================================

def test_minimal_runs(minimal_output):
    assert minimal_output["rc"] == 0, (
        f"Minimal pipeline failed: {minimal_output['stderr']}"
    )


def test_minimal_no_metrics_file(minimal_output):
    assert not os.path.exists(
        os.path.join(minimal_output["output_dir"], "metrics.json")
    ), "metrics.json should not exist when no labels/predictions provided"


def test_minimal_feature_keys(minimal_output):
    assert set(minimal_output["features"].keys()) == {"MAV", "ZC", "SSC", "WL"}


def test_minimal_summary(minimal_output):
    s = minimal_output["summary"]
    assert s["num_channels"] == 1
    assert s["num_windows"] == 19  # (500-50)//25 + 1
    assert set(s["features_extracted"]) == {"MAV", "ZC", "SSC", "WL"}


def test_minimal_mav_values(minimal_output):
    w = minimal_output["ref_windows"]
    expected = ref_mav(w)
    actual = np.array(minimal_output["features"]["MAV"])
    np.testing.assert_allclose(actual, expected, rtol=1e-6)


def test_minimal_wl_values(minimal_output):
    w = minimal_output["ref_windows"]
    expected = ref_wl(w)
    actual = np.array(minimal_output["features"]["WL"])
    np.testing.assert_allclose(actual, expected, rtol=1e-6)


# ============================================================
# Tests: TDPSD + deduplication (2-channel, different window params)
# ============================================================

def test_tdpsd_alt_runs(tdpsd_output):
    assert tdpsd_output["rc"] == 0, (
        f"TDPSD pipeline failed: {tdpsd_output['stderr']}"
    )


def test_tdpsd_alt_feature_keys(tdpsd_output):
    assert set(tdpsd_output["features"].keys()) == {
        "M0", "M2", "M4", "SPARSI", "IRF", "WLF"
    }


def test_tdpsd_alt_dedup(tdpsd_output):
    """Config requests both TDPSD group and individual M0 — deduplicated to 6 features."""
    s = tdpsd_output["summary"]
    assert len(s["features_extracted"]) == 6
    assert s["features_extracted"].count("M0") == 1


def test_tdpsd_alt_m0(tdpsd_output):
    w = tdpsd_output["ref_windows"]
    expected = ref_m0(w)
    actual = np.array(tdpsd_output["features"]["M0"])
    assert np.all(np.abs(actual) <= 1.0 + 1e-10), "M0 out of [-1,1]"
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


def test_tdpsd_alt_sparsi(tdpsd_output):
    w = tdpsd_output["ref_windows"]
    expected = ref_sparsi(w)
    actual = np.array(tdpsd_output["features"]["SPARSI"])
    assert np.all(np.abs(actual) <= 1.0 + 1e-10), "SPARSI out of [-1,1]"
    np.testing.assert_allclose(actual, expected, rtol=1e-5)


# ============================================================
# Tests: Highpass filter + FUZZYEN (3-channel)
# ============================================================

def test_highpass_runs(highpass_output):
    assert highpass_output["rc"] == 0, (
        f"Highpass pipeline failed: {highpass_output['stderr']}"
    )


def test_highpass_feature_keys(highpass_output):
    assert set(highpass_output["features"].keys()) == {
        "MAV", "ZC", "SSC", "WL", "FUZZYEN"
    }


def test_highpass_summary(highpass_output):
    s = highpass_output["summary"]
    assert s["num_channels"] == 3
    # (600-128)//64 + 1 = 8
    assert s["num_windows"] == 8
    assert set(s["features_extracted"]) == {"MAV", "ZC", "SSC", "WL", "FUZZYEN"}


def test_highpass_mav(highpass_output):
    w = highpass_output["ref_windows"]
    expected = ref_mav(w)
    actual = np.array(highpass_output["features"]["MAV"])
    np.testing.assert_allclose(actual, expected, rtol=1e-6)


def test_highpass_fuzzyen_shape(highpass_output):
    fe = np.array(highpass_output["features"]["FUZZYEN"])
    assert fe.shape == (8, 3), f"Expected (8,3), got {fe.shape}"


def test_highpass_fuzzyen_finite(highpass_output):
    fe = np.array(highpass_output["features"]["FUZZYEN"])
    assert np.all(np.isfinite(fe)), "FUZZYEN contains non-finite values"


def test_highpass_fuzzyen_values(highpass_output):
    w = highpass_output["ref_windows"]
    expected = ref_fuzzyen(w)
    actual = np.array(highpass_output["features"]["FUZZYEN"])
    np.testing.assert_allclose(actual, expected, rtol=1e-4)
