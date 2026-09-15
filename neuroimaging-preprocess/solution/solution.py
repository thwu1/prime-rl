#!/usr/bin/env python3

"""Reference solution: bias field correction + spatial conformance pipeline.

Strategy
--------
1. Resample to axis-aligned RAS+ at 2 mm isotropic (nibabel.processing).
2. Estimate the multiplicative bias field by fitting a 3-D polynomial
   surface (order 3) to the log-intensity residuals within each tissue
   class.  This is a simplified variant of the approach described in
   Van Leemput et al. 1999, and mirrors the polynomial-basis model used
   by TorchIO's RandomBiasField.
3. Correct by dividing the image by the estimated field.
4. Z-normalize over the brain mask.
5. Crop to brain bounding box + 4-voxel padding, updating the affine.
6. Save outputs and compute quality metrics.
"""

import json
import os

import nibabel as nib
import numpy as np
from nibabel.processing import resample_to_output


# -------------------------------------------------------------------------
# Bias-field estimation
# -------------------------------------------------------------------------

def estimate_bias_field(data, labels, order=3):
    """Estimate a multiplicative bias field via polynomial surface fitting.

    For each tissue class the mean log-intensity is computed.  The
    log-residuals (observed minus expected log-intensity) are then
    regressed against a polynomial design matrix of the given *order*.
    The fitted surface approximates the spatially-smooth log-bias-field.

    Parameters
    ----------
    data : ndarray, shape (X, Y, Z)
        Image intensities (positive where brain tissue is present).
    labels : ndarray, shape (X, Y, Z)
        Integer label map (0=bg, 1=CSF, 2=GM, 3=WM).
    order : int
        Maximum total polynomial degree.

    Returns
    -------
    bias_field : ndarray, shape (X, Y, Z), float32
        Estimated multiplicative bias field (all values > 0).
    """
    brain_mask = labels > 0
    shape = data.shape

    # Normalised coordinate grids in [-1, 1]
    coords = [np.linspace(-1, 1, s) for s in shape]
    meshes = np.meshgrid(*coords, indexing='ij')

    # --- Build polynomial design matrix for brain voxels ---
    brain_terms = []
    for xo in range(order + 1):
        for yo in range(order + 1 - xo):
            for zo in range(order + 1 - (xo + yo)):
                term = meshes[0] ** xo * meshes[1] ** yo * meshes[2] ** zo
                brain_terms.append(term[brain_mask])

    X = np.array(brain_terms).T  # (n_brain, n_terms)

    # --- Log-intensity and per-tissue expected values ---
    brain_data = data[brain_mask].astype(np.float64)
    log_data = np.log(np.maximum(brain_data, 1.0))

    brain_labels = labels[brain_mask]
    expected = np.zeros(brain_mask.sum(), dtype=np.float64)
    for tid in (1, 2, 3):
        tmask = brain_labels == tid
        if tmask.sum() > 0:
            expected[tmask] = log_data[tmask].mean()

    # --- Least-squares fit of polynomial to residuals ---
    residuals = log_data - expected
    coeffs, _, _, _ = np.linalg.lstsq(X, residuals, rcond=None)

    # --- Evaluate fitted log-bias over the full volume ---
    full_terms = []
    for xo in range(order + 1):
        for yo in range(order + 1 - xo):
            for zo in range(order + 1 - (xo + yo)):
                term = meshes[0] ** xo * meshes[1] ** yo * meshes[2] ** zo
                full_terms.append(term.ravel())

    X_full = np.array(full_terms).T
    log_bias = (X_full @ coeffs).reshape(shape)

    return np.exp(log_bias).astype(np.float32)


# -------------------------------------------------------------------------
# Main pipeline
# -------------------------------------------------------------------------

def main():
    os.makedirs("/app/output", exist_ok=True)

    # --- Load ---
    phantom = nib.load("/app/data/phantom.nii.gz")
    labels_img = nib.load("/app/data/labels.nii.gz")

    # --- Stage 1: resample to axis-aligned RAS+ at 2 mm isotropic ---
    phantom_iso = resample_to_output(phantom, voxel_sizes=(2.0, 2.0, 2.0), order=3)
    labels_iso_raw = resample_to_output(labels_img, voxel_sizes=(2.0, 2.0, 2.0), order=0)

    ldata = np.round(labels_iso_raw.get_fdata()).astype(np.int16)
    ldata = np.clip(ldata, 0, 3)

    img_data = phantom_iso.get_fdata().astype(np.float64)

    # --- Stage 2: estimate and correct multiplicative bias field ---
    bias_field = estimate_bias_field(img_data, ldata, order=3)
    img_corrected = img_data / bias_field

    # --- Stage 3: z-score normalisation (brain mask) ---
    brain_mask = ldata > 0
    mu = img_corrected[brain_mask].mean()
    sigma = img_corrected[brain_mask].std()
    img_norm = ((img_corrected - mu) / sigma).astype(np.float32)

    # --- Stage 4: crop to brain bbox + 4-voxel padding ---
    coords = np.argwhere(ldata > 0)
    min_c = coords.min(axis=0)
    max_c = coords.max(axis=0)

    pad = 4
    min_crop = np.maximum(min_c - pad, 0)
    max_crop = np.minimum(max_c + pad + 1, np.array(img_norm.shape))

    sl = tuple(slice(int(mn), int(mx)) for mn, mx in zip(min_crop, max_crop))
    c_img = img_norm[sl]
    c_lbl = ldata[sl]
    c_bf = bias_field[sl]

    # Update affine origin for crop offset
    src_aff = phantom_iso.affine.copy()
    new_aff = src_aff.copy()
    new_aff[:3, 3] = src_aff[:3, :3] @ min_crop.astype(np.float64) + src_aff[:3, 3]

    # --- Save ---
    nib.save(nib.Nifti1Image(c_img, new_aff), "/app/output/corrected.nii.gz")
    nib.save(nib.Nifti1Image(c_lbl, new_aff), "/app/output/labels_corrected.nii.gz")
    nib.save(
        nib.Nifti1Image(c_bf.astype(np.float32), new_aff),
        "/app/output/bias_field.nii.gz",
    )

    # --- Quality metrics ---
    wm = c_img[c_lbl == 3]
    gm = c_img[c_lbl == 2]
    bg = c_img[c_lbl == 0]

    wm_std = float(wm.std())
    gm_std = float(gm.std())

    snr = float(wm.mean() / bg.std()) if bg.std() > 0 else 0.0
    cnr = float(
        abs(gm.mean() - wm.mean()) / np.sqrt(0.5 * (gm.var() + wm.var()))
    )
    fisher = float((wm.mean() - gm.mean()) ** 2 / (wm.var() + gm.var()))

    brain_ijk = np.argwhere(c_lbl > 0).astype(np.float64)
    centroid_vox = brain_ijk.mean(axis=0)
    centroid_ras = (new_aff[:3, :3] @ centroid_vox + new_aff[:3, 3]).tolist()

    spacing = np.sqrt(np.sum(new_aff[:3, :3] ** 2, axis=0)).tolist()
    orientation = "".join(nib.orientations.aff2axcodes(new_aff))

    brain_bf = c_bf[c_lbl > 0]

    metrics = {
        "shape": list(c_img.shape),
        "spacing": [round(s, 4) for s in spacing],
        "orientation": orientation,
        "wm_std": round(wm_std, 6),
        "gm_std": round(gm_std, 6),
        "bias_field_range": [
            round(float(brain_bf.min()), 4),
            round(float(brain_bf.max()), 4),
        ],
        "snr": round(snr, 4),
        "cnr": round(cnr, 4),
        "brain_center_ras": [round(c, 4) for c in centroid_ras],
        "fisher_gm_wm": round(fisher, 4),
    }

    with open("/app/output/metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"Pipeline complete.  shape={metrics['shape']}  orient={orientation}")
    print(f"  WM std={wm_std:.4f}  GM std={gm_std:.4f}")
    print(f"  Bias range={metrics['bias_field_range']}")
    print(f"  SNR={snr:.4f}  CNR={cnr:.4f}  Fisher={fisher:.4f}")
    print(f"  Brain centre RAS={metrics['brain_center_ras']}")


if __name__ == "__main__":
    main()
