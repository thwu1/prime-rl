#!/usr/bin/env python3
"""Generate synthetic radiotherapy planning data for dosimetric audit task."""
import numpy as np
import SimpleITK as sitk
import os

# Grid parameters (non-isotropic spacing — critical for correct Dcc computation)
NX, NY, NZ = 48, 48, 48
SX, SY, SZ = 2.5, 2.5, 3.0  # mm

# Coordinate grids in physical mm (numpy z,y,x ordering)
x = np.arange(NX) * SX
y = np.arange(NY) * SY
z = np.arange(NZ) * SZ
Z, Y, X = np.meshgrid(z, y, x, indexing='ij')

# Grid center
CX, CY, CZ = (NX - 1) * SX / 2.0, (NY - 1) * SY / 2.0, (NZ - 1) * SZ / 2.0


def save_nifti(arr, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing([SX, SY, SZ])
    img.SetOrigin([0.0, 0.0, 0.0])
    sitk.WriteImage(img, path)


def sphere(c, r):
    d = np.sqrt((X - c[0])**2 + (Y - c[1])**2 + (Z - c[2])**2)
    return (d <= r).astype(np.uint8)


def dose_plateau(c, R, A, sigma, iv=0.02):
    """Plateau inside PTV with small hotspot variation, exponential falloff outside."""
    d = np.sqrt((X - c[0])**2 + (Y - c[1])**2 + (Z - c[2])**2)
    din = A * (1.0 + iv * (1.0 - (d / R)**2))
    dout = A * np.exp(-np.maximum(d - R, 0.0) / sigma)
    return np.where(d <= R, din, dout).astype(np.float64)


def dose_gauss(c, sigma, A):
    """Simple Gaussian dose — non-uniform inside PTV."""
    dsq = (X - c[0])**2 + (Y - c[1])**2 + (Z - c[2])**2
    return (A * np.exp(-dsq / (2 * sigma**2))).astype(np.float64)


BASE = "/app/data"

# --- Patient A: plateau dose, 6% hotspot, cord close to PTV ---
# Includes an "External" body contour (should not be analyzed as OAR)
save_nifti(dose_plateau((CX, CY, CZ), 18, 74.0, 15, 0.06),
           f"{BASE}/patient_A/dose.nii.gz")
for name, c, r in [
    ("PTV_7000",   (CX, CY, CZ),      18),
    ("brainstem",  (CX, CY, CZ + 45),   8),
    ("lt_parotid", (CX - 35, CY, CZ),  12),
    ("rt_parotid", (CX + 35, CY, CZ),  12),
    ("cord",       (CX, CY - 30, CZ),   6),
    ("External",   (CX, CY, CZ),       55),
]:
    save_nifti(sphere(c, r), f"{BASE}/patient_A/structures/{name}.nii.gz")

# --- Patient B: plateau dose, well-separated OARs, tight falloff ---
# Includes a "BODY" contour (should not be analyzed as OAR)
save_nifti(dose_plateau((CX, CY, CZ), 17, 73.5, 12, 0.02),
           f"{BASE}/patient_B/dose.nii.gz")
for name, c, r in [
    ("PTV70",      (CX, CY, CZ),      17),
    ("Brain_Stem", (CX, CY, CZ + 48),   9),
    ("L_PAROTID",  (CX - 38, CY, CZ),  11),
    ("R_Parotid",  (CX + 38, CY, CZ),  11),
    ("SpinalCord", (CX, CY - 35, CZ),   7),
    ("BODY",       (CX, CY, CZ),       55),
]:
    save_nifti(sphere(c, r), f"{BASE}/patient_B/structures/{name}.nii.gz")

# --- Patient C: Gaussian dose (poor PTV coverage), cord close ---
save_nifti(dose_gauss((CX, CY, CZ), 22, 75.0),
           f"{BASE}/patient_C/dose.nii.gz")
for name, c, r in [
    ("ptv_70gy",      (CX, CY, CZ),      16),
    ("BRAINSTEM",     (CX, CY, CZ + 40),   7),
    ("Parotid_Left",  (CX - 32, CY, CZ),  10),
    ("Parotid_Right", (CX + 32, CY, CZ),  10),
    ("SC",            (CX, CY - 25, CZ),   5),
]:
    save_nifti(sphere(c, r), f"{BASE}/patient_C/structures/{name}.nii.gz")

# --- Patient D: plateau dose BUT stored in cGy (x100) ---
# Agent must detect this anomaly and convert to Gy for reporting
dose_cgy = dose_plateau((CX, CY, CZ), 16, 73.0, 14, 0.03) * 100.0
save_nifti(dose_cgy, f"{BASE}/patient_D/dose.nii.gz")
for name, c, r in [
    ("target_70gy", (CX, CY, CZ),      16),
    ("bstem",       (CX, CY, CZ + 42),   8),
    ("par_L",       (CX - 34, CY, CZ),  11),
    ("par_R",       (CX + 34, CY, CZ),  11),
    ("spinal",      (CX, CY - 28, CZ),   6),
]:
    save_nifti(sphere(c, r), f"{BASE}/patient_D/structures/{name}.nii.gz")

print("Generated synthetic RT data for 4 patients.")
