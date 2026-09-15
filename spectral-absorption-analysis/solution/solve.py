#!/usr/bin/env python3
"""
USGS Spectral Library Version 7 — Continuum Removal & Mixture Unmixing Pipeline.

Downloads splib07a ASCII data from ScienceBase, performs continuum removal
and absorption feature extraction on five mineral spectra, creates a
synthetic mixture, and identifies components via SAM + least-squares unmixing.
"""


import os
import sys
import json
import csv
import re
import zipfile
import urllib.request
import numpy as np
from scipy.signal import argrelextrema
from scipy.optimize import nnls
from pathlib import Path

BAD_BAND_THRESHOLD = -1.0e30
RANDOM_SEED = 42
OUTPUT_DIR = "/app/output"
CR_DIR = os.path.join(OUTPUT_DIR, "continuum_removed")
SCIENCEBASE_ITEM = "586e8c88e4b0f5ce109fccae"

# Mineral search: name -> list of search term sets (tried in order).
# Each set is a list of substrings that ALL must appear in the filename.
MINERAL_SEARCH = {
    "Alunite": [
        ["Alunite", "ASD", "AREF"],
    ],
    "Calcite": [
        ["Calcite", "ASD", "AREF"],
    ],
    "Kaolinite": [
        ["Kaolinite", "KGa-1", "ASD", "AREF"],
        ["Kaolinite", "KGa", "ASD", "AREF"],
        ["Kaolinite", "ASD", "AREF"],
    ],
    "Montmorillonite": [
        ["Montmorillonite", "SWy", "ASD", "AREF"],
        ["Montmorillonite", "ASD", "AREF"],
    ],
    "Muscovite": [
        ["Muscovite", "ASD", "AREF"],
    ],
}


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy numeric types."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


# ---------------------------------------------------------------------------
# Data acquisition
# ---------------------------------------------------------------------------

def download_and_extract():
    """Download and extract ASCIIdata_splib07a.zip from ScienceBase."""
    zip_path = "/app/ASCIIdata_splib07a.zip"
    data_dir = "/app/splib07a"
    marker = os.path.join(data_dir, ".extracted")

    if not os.path.exists(zip_path):
        api_url = (
            f"https://www.sciencebase.gov/catalog/item/{SCIENCEBASE_ITEM}"
            "?format=json"
        )
        print(f"Querying ScienceBase API: {api_url}")
        req = urllib.request.Request(
            api_url,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            item = json.loads(resp.read().decode())

        dl_url = None
        for f in item.get("files", []):
            if f.get("name") == "ASCIIdata_splib07a.zip":
                dl_url = f.get("downloadUri") or f.get("url")
                break
        if dl_url is None:
            # Fallback: direct download URL
            dl_url = (
                "https://www.sciencebase.gov/catalog/file/get/"
                f"{SCIENCEBASE_ITEM}?f=__disk__a7%2F4f%2F91%2F"
                "a74f913e0b7d1b8123ad059e52506a02b75a2832"
            )

        print(f"Downloading {dl_url} ...")
        urllib.request.urlretrieve(dl_url, zip_path)
        print(f"Downloaded {os.path.getsize(zip_path):,} bytes")

    if not os.path.exists(marker):
        print("Extracting archive ...")
        os.makedirs(data_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(data_dir)
        Path(marker).touch()
        print("Extraction complete")

    return data_dir


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _txt_files_under(root):
    """Yield all .txt file paths under *root*, recursively."""
    for dirpath, _, filenames in os.walk(root):
        for fn in sorted(filenames):
            if fn.lower().endswith(".txt"):
                yield os.path.join(dirpath, fn)


def find_wavelength_file(data_dir):
    """Locate the ASD wavelength file."""
    for path in _txt_files_under(data_dir):
        bn = os.path.basename(path)
        if "Wavelengths" in bn and "ASD" in bn.upper():
            return path
    return None


def _extract_sample_id(filename):
    """Extract a short sample identifier from a splib07a filename."""
    bn = os.path.basename(filename)
    # Remove prefix and suffix
    bn = bn.replace("splib07a_", "")
    bn = re.sub(r'_ASD.*$', '', bn)
    return bn


def find_mineral_files(data_dir):
    """Return {mineral_name: filepath} for each mineral."""
    candidates = []
    for path in _txt_files_under(data_dir):
        if "ChapterM" in path:
            candidates.append(path)

    found = {}
    for mineral_name, search_sets in MINERAL_SEARCH.items():
        best = None
        for terms in search_sets:
            for cpath in candidates:
                bn = os.path.basename(cpath).upper()
                # Skip wavelength / bandpass files
                if "WAVELENGTH" in bn or "BANDPASS" in bn:
                    continue
                if all(t.upper() in bn for t in terms):
                    best = cpath
                    break
            if best is not None:
                break
        if best is not None:
            found[mineral_name] = best
        else:
            print(f"WARNING: no ASD spectrum found for {mineral_name}")

    return found


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_values(filepath):
    """Read one-float-per-line file, return numpy array."""
    vals = []
    with open(filepath) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                vals.append(float(line))
            except ValueError:
                continue
    return np.array(vals, dtype=np.float64)


def filter_bad_bands(wavelengths, reflectance):
    """Remove channels where reflectance equals the bad-band sentinel."""
    mask = reflectance > BAD_BAND_THRESHOLD
    return wavelengths[mask], reflectance[mask]


# ---------------------------------------------------------------------------
# Continuum removal (upper convex hull)
# ---------------------------------------------------------------------------

def upper_convex_hull_indices(x, y):
    """
    Return indices of the upper convex hull for points sorted by x.
    Uses Andrew's monotone chain algorithm (upper-hull pass).
    """
    n = len(x)
    if n < 2:
        return list(range(n))

    idx = [0]
    for i in range(1, n):
        while len(idx) >= 2:
            k, j = idx[-2], idx[-1]
            # Cross product: positive means left turn (j below line k->i)
            cross = ((x[j] - x[k]) * (y[i] - y[k])
                     - (y[j] - y[k]) * (x[i] - x[k]))
            if cross >= 0:
                idx.pop()
            else:
                break
        idx.append(i)
    return idx


def continuum_removal(wavelengths, reflectance):
    """
    Compute continuum-removed reflectance via the upper convex hull method.
    Returns (cr, continuum) where cr = reflectance / continuum, clipped to [0, 1].
    """
    hull = upper_convex_hull_indices(wavelengths, reflectance)
    continuum = np.interp(wavelengths, wavelengths[hull], reflectance[hull])
    continuum = np.maximum(continuum, 1e-12)
    cr = reflectance / continuum
    # Clip to physically valid range
    cr = np.clip(cr, 0.0, 1.0)
    return cr, continuum


# ---------------------------------------------------------------------------
# Absorption feature extraction
# ---------------------------------------------------------------------------

def extract_features(wavelengths, cr, min_depth=0.02):
    """
    Find absorption features in a continuum-removed spectrum.
    Returns list of dicts with center_um, depth, fwhm_um, area.
    """
    n = len(wavelengths)
    if n < 10:
        return []

    order = max(3, n // 80)
    minima = argrelextrema(cr, np.less, order=order)[0]

    features = []
    for mi in minima:
        depth = float(1.0 - cr[mi])
        if depth < min_depth:
            continue

        center = float(wavelengths[mi])
        half_level = 1.0 - depth / 2.0

        # FWHM: left boundary
        left_wl = float(wavelengths[0])
        for j in range(mi - 1, -1, -1):
            if cr[j] >= half_level:
                denom = float(cr[j] - cr[j + 1])
                if abs(denom) > 1e-15:
                    frac = (half_level - float(cr[j + 1])) / denom
                else:
                    frac = 0.5
                left_wl = float(wavelengths[j + 1]) + frac * float(wavelengths[j] - wavelengths[j + 1])
                break

        # FWHM: right boundary
        right_wl = float(wavelengths[-1])
        for j in range(mi + 1, n):
            if cr[j] >= half_level:
                denom = float(cr[j] - cr[j - 1])
                if abs(denom) > 1e-15:
                    frac = (half_level - float(cr[j - 1])) / denom
                else:
                    frac = 0.5
                right_wl = float(wavelengths[j - 1]) + frac * float(wavelengths[j] - wavelengths[j - 1])
                break

        fwhm = max(right_wl - left_wl, float(wavelengths[1] - wavelengths[0]))

        # Integrated area via trapezoidal rule
        mask = (wavelengths >= left_wl) & (wavelengths <= right_wl)
        if np.sum(mask) > 1:
            area = float(np.trapezoid(1.0 - cr[mask], wavelengths[mask]))
        else:
            area = depth * fwhm * 0.5

        features.append({
            "center_um": round(center, 4),
            "depth":     round(depth, 4),
            "fwhm_um":   round(fwhm, 4),
            "area":      round(area, 6),
        })

    features.sort(key=lambda f: -f["depth"])
    return features


# ---------------------------------------------------------------------------
# Spectral Angle Mapper
# ---------------------------------------------------------------------------

def spectral_angle(a, b):
    """SAM distance in radians."""
    dot = float(np.dot(a, b))
    norms = float(np.linalg.norm(a)) * float(np.linalg.norm(b))
    if norms < 1e-15:
        return float(np.pi / 2.0)
    return float(np.arccos(np.clip(dot / norms, -1.0, 1.0)))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    os.makedirs(CR_DIR, exist_ok=True)

    # ---- 1. Download & extract ----
    data_dir = download_and_extract()

    # ---- 2. Locate wavelength file ----
    wl_file = find_wavelength_file(data_dir)
    if wl_file is None:
        raise RuntimeError("ASD wavelength file not found")
    print(f"Wavelength file: {wl_file}")

    wavelengths_full = parse_values(wl_file)
    if wavelengths_full.max() > 100:   # values in nm -> convert to um
        wavelengths_full /= 1000.0
        print("Converted wavelengths from nm to um")
    print(f"Channels: {len(wavelengths_full)}, range: "
          f"{wavelengths_full.min():.4f} - {wavelengths_full.max():.4f} um")

    # ---- 3. Locate mineral spectra ----
    mineral_files = find_mineral_files(data_dir)
    print(f"\nFound {len(mineral_files)}/5 mineral spectra:")
    for mk, mp in mineral_files.items():
        print(f"  {mk}: {os.path.basename(mp)}")

    if len(mineral_files) < 5:
        print("WARNING: fewer than 5 minerals found, proceeding with available spectra")

    # ---- 4. Parse spectra, continuum removal, feature extraction ----
    spectra = {}
    all_features = {}

    for mineral_name, filepath in mineral_files.items():
        refl = parse_values(filepath)
        min_len = min(len(wavelengths_full), len(refl))
        wl = wavelengths_full[:min_len].copy()
        r = refl[:min_len].copy()

        wl_clean, r_clean = filter_bad_bands(wl, r)
        print(f"\n{mineral_name}: {len(r_clean)}/{len(r)} valid channels")
        spectra[mineral_name] = {"wl": wl_clean, "refl": r_clean}

        # Restrict to 1.0-2.5 um for analysis
        mask = (wl_clean >= 1.0) & (wl_clean <= 2.5)
        wl_range = wl_clean[mask]
        r_range = r_clean[mask]
        if len(wl_range) < 10:
            print(f"  Insufficient data in 1.0-2.5 um")
            all_features[mineral_name] = []
            continue

        cr, _ = continuum_removal(wl_range, r_range)

        # Save continuum-removed CSV
        cr_path = os.path.join(CR_DIR, f"{mineral_name}.csv")
        with open(cr_path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["wavelength_um", "cr_reflectance"])
            for w, c in zip(wl_range, cr):
                writer.writerow([f"{float(w):.6f}", f"{float(c):.6f}"])

        features = extract_features(wl_range, cr, min_depth=0.02)
        all_features[mineral_name] = features
        print(f"  {len(features)} absorption features:")
        for feat in features[:6]:
            print(f"    {feat['center_um']:.3f} um  depth={feat['depth']:.3f}  "
                  f"FWHM={feat['fwhm_um']:.3f}")

    # Save absorption features
    feat_path = os.path.join(OUTPUT_DIR, "absorption_features.json")
    with open(feat_path, "w") as fh:
        json.dump(all_features, fh, indent=2, cls=NumpyEncoder)
    print(f"\nWrote {feat_path}")

    # ---- 5. Mixture creation & identification ----
    np.random.seed(RANDOM_SEED)

    kao_key = next((k for k in spectra if "kaolinite" in k.lower()), None)
    mont_key = next((k for k in spectra if "montmorillonite" in k.lower()), None)
    if kao_key is None or mont_key is None:
        raise RuntimeError(f"Missing mixture endpoints: kao={kao_key}, mont={mont_key}")

    ref_wl = spectra[kao_key]["wl"]
    kao_r = spectra[kao_key]["refl"]
    mont_r = np.interp(ref_wl, spectra[mont_key]["wl"], spectra[mont_key]["refl"])

    mixture = 0.6 * kao_r + 0.4 * mont_r
    mixture += np.random.normal(0, 0.005, len(mixture))

    # SAM against every library spectrum
    sam_angles = {}
    for mk, md in spectra.items():
        lib_r = np.interp(ref_wl, md["wl"], md["refl"])
        valid = (mixture > 0) & (lib_r > 0)
        if valid.sum() < 10:
            sam_angles[mk] = float(np.pi / 2)
        else:
            sam_angles[mk] = round(spectral_angle(mixture[valid], lib_r[valid]), 6)

    sorted_sam = sorted(sam_angles.items(), key=lambda x: x[1])
    identified = [s[0] for s in sorted_sam[:2]]

    print(f"\nSAM ranking:")
    for mk, ang in sorted_sam:
        print(f"  {mk}: {ang:.4f} rad")
    print(f"Identified: {identified}")

    # Least-squares unmixing (non-negative) with top-2 components
    s1 = np.interp(ref_wl, spectra[identified[0]]["wl"],
                   spectra[identified[0]]["refl"])
    s2 = np.interp(ref_wl, spectra[identified[1]]["wl"],
                   spectra[identified[1]]["refl"])
    A = np.column_stack([s1, s2])
    valid = (mixture > 0) & (s1 > 0) & (s2 > 0)
    coeffs, _ = nnls(A[valid], mixture[valid])

    total = float(coeffs[0] + coeffs[1])
    if total > 1e-10:
        props = {
            identified[0]: round(float(coeffs[0]) / total, 4),
            identified[1]: round(float(coeffs[1]) / total, 4),
        }
    else:
        props = {identified[0]: 0.5, identified[1]: 0.5}

    print(f"Estimated proportions: {props}")

    mixture_result = {
        "identified_minerals": identified,
        "spectral_angles": {k: float(v) for k, v in sam_angles.items()},
        "mixing_proportions": {k: float(v) for k, v in props.items()},
    }
    mix_path = os.path.join(OUTPUT_DIR, "mixture_identification.json")
    with open(mix_path, "w") as fh:
        json.dump(mixture_result, fh, indent=2, cls=NumpyEncoder)
    print(f"Wrote {mix_path}")

    print("\n=== Pipeline complete ===")


if __name__ == "__main__":
    main()
