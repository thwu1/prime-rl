
"""Tests for brain MRI conformance pipeline with bias-field correction."""

import json
import os

import nibabel as nib
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def corrected():
    path = "/app/output/corrected.nii.gz"
    assert os.path.exists(path), f"Output image not found: {path}"
    return nib.load(path)


@pytest.fixture(scope="module")
def labels_corrected():
    path = "/app/output/labels_corrected.nii.gz"
    assert os.path.exists(path), f"Output labels not found: {path}"
    return nib.load(path)


@pytest.fixture(scope="module")
def bias_field():
    path = "/app/output/bias_field.nii.gz"
    assert os.path.exists(path), f"Bias field not found: {path}"
    return nib.load(path)


@pytest.fixture(scope="module")
def metrics():
    path = "/app/output/metrics.json"
    assert os.path.exists(path), f"Metrics file not found: {path}"
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# output file existence
# ---------------------------------------------------------------------------

def test_output_files_exist():
    for name in (
        "corrected.nii.gz",
        "labels_corrected.nii.gz",
        "bias_field.nii.gz",
        "metrics.json",
    ):
        assert os.path.exists(f"/app/output/{name}"), f"Missing output: {name}"


# ---------------------------------------------------------------------------
# orientation and geometry
# ---------------------------------------------------------------------------

def test_orientation_is_ras(corrected):
    codes = nib.orientations.aff2axcodes(corrected.affine)
    assert codes == ("R", "A", "S"), (
        f"Expected RAS orientation, got {''.join(codes)}"
    )


def test_affine_is_diagonal(corrected):
    """Output affine must be axis-aligned (no off-diagonal rotation)."""
    M = corrected.affine[:3, :3]
    off_diag = M.copy()
    np.fill_diagonal(off_diag, 0)
    assert np.allclose(off_diag, 0, atol=0.05), (
        f"Affine has significant off-diagonal elements:\n{M}"
    )


def test_spacing_is_isotropic_2mm(corrected):
    spacing = np.sqrt(np.sum(corrected.affine[:3, :3] ** 2, axis=0))
    np.testing.assert_allclose(
        spacing, [2.0, 2.0, 2.0], atol=0.05,
        err_msg=f"Spacing {spacing} is not isotropic 2 mm",
    )


# ---------------------------------------------------------------------------
# label integrity
# ---------------------------------------------------------------------------

def test_labels_are_valid(labels_corrected):
    data = np.round(labels_corrected.get_fdata()).astype(int)
    unique = set(np.unique(data))
    invalid = unique - {0, 1, 2, 3}
    assert not invalid, f"Invalid label values: {invalid}"


def test_labels_have_all_tissues(labels_corrected):
    data = np.round(labels_corrected.get_fdata()).astype(int)
    unique = set(np.unique(data))
    assert {0, 1, 2, 3}.issubset(unique), f"Missing tissue labels; got {unique}"


# ---------------------------------------------------------------------------
# data quality
# ---------------------------------------------------------------------------

def test_no_nan_or_inf(corrected):
    data = corrected.get_fdata()
    assert not np.any(np.isnan(data)), "Image contains NaN"
    assert not np.any(np.isinf(data)), "Image contains Inf"


# ---------------------------------------------------------------------------
# z-normalisation
# ---------------------------------------------------------------------------

def test_znormalization(corrected, labels_corrected):
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    brain = data[ldata > 0]
    assert abs(brain.mean()) < 0.15, (
        f"Brain mean after z-norm is {brain.mean():.4f}, expected ~0"
    )
    assert abs(brain.std() - 1.0) < 0.15, (
        f"Brain std after z-norm is {brain.std():.4f}, expected ~1"
    )


# ---------------------------------------------------------------------------
# tissue homogeneity — these tests REQUIRE bias-field correction
# ---------------------------------------------------------------------------

def test_wm_homogeneity(corrected, labels_corrected):
    """Within-WM intensity std must be low after correction.

    Without bias-field correction the multiplicative inhomogeneity
    inflates within-tissue variance well above the threshold.
    """
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    wm = data[ldata == 3]
    assert len(wm) > 100, "Too few WM voxels"
    wm_std = float(wm.std())
    assert wm_std < 0.20, (
        f"WM intensity std = {wm_std:.4f} exceeds threshold 0.20.  "
        "This typically indicates missing or inadequate bias-field correction."
    )


def test_gm_homogeneity(corrected, labels_corrected):
    """Within-GM intensity std must be low after correction."""
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    gm = data[ldata == 2]
    assert len(gm) > 100, "Too few GM voxels"
    gm_std = float(gm.std())
    assert gm_std < 0.25, (
        f"GM intensity std = {gm_std:.4f} exceeds threshold 0.25.  "
        "This typically indicates missing or inadequate bias-field correction."
    )


def test_tissue_separability(corrected, labels_corrected):
    """Fisher discriminant between GM and WM must be high.

    Uncorrected bias-field inflates within-class variance, collapsing
    the Fisher ratio below threshold.
    """
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    wm = data[ldata == 3]
    gm = data[ldata == 2]
    fisher = (wm.mean() - gm.mean()) ** 2 / (wm.var() + gm.var())
    assert fisher > 6.0, (
        f"Fisher discriminant GM/WM = {fisher:.2f}, below threshold 6.0.  "
        "Tissue classes are not well-separated."
    )


# ---------------------------------------------------------------------------
# bias-field output validation
# ---------------------------------------------------------------------------

def test_bias_field_positive(bias_field):
    data = bias_field.get_fdata()
    assert np.all(data > 0), "Bias field must be strictly positive (multiplicative)"


def test_bias_field_range_plausible(bias_field, labels_corrected):
    bf = bias_field.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    brain_bf = bf[ldata > 0]
    assert brain_bf.min() > 0.3, (
        f"Bias-field min {brain_bf.min():.3f} implausibly low"
    )
    assert brain_bf.max() < 3.0, (
        f"Bias-field max {brain_bf.max():.3f} implausibly high"
    )


def test_bias_field_smooth(bias_field):
    """Adjacent-voxel relative change must be small (smooth field)."""
    bf = bias_field.get_fdata()
    for axis in range(3):
        d = np.abs(np.diff(bf, axis=axis))
        base = np.minimum(
            np.take(bf, range(bf.shape[axis] - 1), axis=axis),
            np.take(bf, range(1, bf.shape[axis]), axis=axis),
        )
        base = np.maximum(base, 0.1)
        rel = d / base
        assert rel.max() < 0.08, (
            f"Bias field changes too rapidly along axis {axis}: "
            f"max relative change = {rel.max():.4f} (threshold 0.08)"
        )


def test_bias_field_spatial_consistency(corrected, bias_field):
    assert bias_field.shape == corrected.shape, (
        f"Bias-field shape {bias_field.shape} != image shape {corrected.shape}"
    )
    np.testing.assert_allclose(
        bias_field.affine, corrected.affine, atol=0.01,
        err_msg="Bias-field affine != image affine",
    )


# ---------------------------------------------------------------------------
# crop validation
# ---------------------------------------------------------------------------

def test_crop_has_padding(labels_corrected):
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    brain = ldata > 0
    for axis in range(3):
        other = tuple(i for i in range(3) if i != axis)
        has_brain = brain.any(axis=other)
        idx = np.where(has_brain)[0]
        assert len(idx) > 0, "No brain voxels found"
        first, last = idx[0], idx[-1]
        end_pad = ldata.shape[axis] - 1 - last
        assert 2 <= first <= 8, (
            f"Axis {axis}: start padding = {first}, expected 2-8"
        )
        assert 2 <= end_pad <= 8, (
            f"Axis {axis}: end padding = {end_pad}, expected 2-8"
        )


def test_shape_is_reasonable(corrected):
    for i, s in enumerate(corrected.shape[:3]):
        assert 30 <= s <= 130, (
            f"Axis {i}: shape {s} outside reasonable range [30, 130]"
        )


# ---------------------------------------------------------------------------
# spatial consistency
# ---------------------------------------------------------------------------

def test_image_label_spatial_consistency(corrected, labels_corrected):
    assert corrected.shape == labels_corrected.shape, (
        f"Shape mismatch: image {corrected.shape} vs labels "
        f"{labels_corrected.shape}"
    )
    np.testing.assert_allclose(
        corrected.affine, labels_corrected.affine, atol=0.01,
        err_msg="Affine mismatch between image and labels",
    )


def test_brain_center_near_origin(corrected, labels_corrected):
    """Phantom centroid was at world origin; must stay near (0,0,0)."""
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    brain_ijk = np.argwhere(ldata > 0).astype(float)
    cen = brain_ijk.mean(axis=0)
    cen_world = corrected.affine[:3, :3] @ cen + corrected.affine[:3, 3]
    for i, c in enumerate(cen_world):
        assert abs(c) < 10.0, (
            f"Brain centroid axis {i} = {c:.2f} mm, expected near 0"
        )


# ---------------------------------------------------------------------------
# metrics.json — key presence
# ---------------------------------------------------------------------------

def test_metrics_required_keys(metrics):
    required = (
        "shape", "spacing", "orientation", "wm_std", "gm_std",
        "bias_field_range", "snr", "cnr", "brain_center_ras", "fisher_gm_wm",
    )
    for key in required:
        assert key in metrics, f"metrics.json missing key: {key}"


# ---------------------------------------------------------------------------
# metrics.json — value checks
# ---------------------------------------------------------------------------

def test_metrics_orientation(metrics):
    assert metrics["orientation"] == "RAS", (
        f"Reported orientation '{metrics['orientation']}' != 'RAS'"
    )


def test_metrics_spacing(metrics):
    np.testing.assert_allclose(
        metrics["spacing"], [2.0, 2.0, 2.0], atol=0.05,
        err_msg=f"Reported spacing {metrics['spacing']} != [2,2,2]",
    )


def test_metrics_snr_range(metrics):
    assert 3.0 < metrics["snr"] < 200.0, (
        f"SNR {metrics['snr']} outside plausible range (3, 200)"
    )


def test_metrics_cnr_range(metrics):
    assert 0.5 < metrics["cnr"] < 50.0, (
        f"CNR {metrics['cnr']} outside plausible range (0.5, 50)"
    )


def test_metrics_brain_center(metrics):
    center = metrics["brain_center_ras"]
    assert len(center) == 3, "brain_center_ras must have 3 elements"
    for i, c in enumerate(center):
        assert abs(c) < 10.0, (
            f"brain_center_ras[{i}] = {c}, expected near 0"
        )


def test_metrics_fisher(metrics):
    assert metrics["fisher_gm_wm"] > 6.0, (
        f"Fisher discriminant {metrics['fisher_gm_wm']:.2f} below threshold 6.0"
    )


def test_metrics_bias_field_range(metrics):
    bfr = metrics["bias_field_range"]
    assert len(bfr) == 2, "bias_field_range must have 2 elements"
    assert 0.3 < bfr[0] < 1.0, (
        f"Bias-field min {bfr[0]} outside (0.3, 1.0)"
    )
    assert 1.0 < bfr[1] < 3.0, (
        f"Bias-field max {bfr[1]} outside (1.0, 3.0)"
    )


# ---------------------------------------------------------------------------
# metrics.json — cross-validation (recompute from output files)
# ---------------------------------------------------------------------------

def test_snr_matches_recomputed(corrected, labels_corrected, metrics):
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    wm = data[ldata == 3]
    bg = data[ldata == 0]
    assert len(bg) > 0 and bg.std() > 0
    snr_re = float(wm.mean() / bg.std())
    rel = abs(snr_re - metrics["snr"]) / max(abs(metrics["snr"]), 1e-6)
    assert rel < 0.10, (
        f"SNR mismatch: recomputed {snr_re:.4f} vs reported {metrics['snr']}"
    )


def test_cnr_matches_recomputed(corrected, labels_corrected, metrics):
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    gm = data[ldata == 2]
    wm = data[ldata == 3]
    cnr_re = float(
        abs(gm.mean() - wm.mean()) / np.sqrt(0.5 * (gm.var() + wm.var()))
    )
    rel = abs(cnr_re - metrics["cnr"]) / max(abs(metrics["cnr"]), 1e-6)
    assert rel < 0.10, (
        f"CNR mismatch: recomputed {cnr_re:.4f} vs reported {metrics['cnr']}"
    )


def test_fisher_matches_recomputed(corrected, labels_corrected, metrics):
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    wm = data[ldata == 3]
    gm = data[ldata == 2]
    f_re = float((wm.mean() - gm.mean()) ** 2 / (wm.var() + gm.var()))
    rel = abs(f_re - metrics["fisher_gm_wm"]) / max(
        abs(metrics["fisher_gm_wm"]), 1e-6
    )
    assert rel < 0.10, (
        f"Fisher mismatch: recomputed {f_re:.4f} vs reported "
        f"{metrics['fisher_gm_wm']}"
    )


def test_wm_std_matches_recomputed(corrected, labels_corrected, metrics):
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    wm_std_re = float(data[ldata == 3].std())
    rel = abs(wm_std_re - metrics["wm_std"]) / max(abs(metrics["wm_std"]), 1e-6)
    assert rel < 0.10, (
        f"WM std mismatch: recomputed {wm_std_re:.6f} vs reported "
        f"{metrics['wm_std']}"
    )


def test_gm_std_matches_recomputed(corrected, labels_corrected, metrics):
    data = corrected.get_fdata()
    ldata = np.round(labels_corrected.get_fdata()).astype(int)
    gm_std_re = float(data[ldata == 2].std())
    rel = abs(gm_std_re - metrics["gm_std"]) / max(abs(metrics["gm_std"]), 1e-6)
    assert rel < 0.10, (
        f"GM std mismatch: recomputed {gm_std_re:.6f} vs reported "
        f"{metrics['gm_std']}"
    )
