Build a spectral analysis tool at `/app/` that characterizes mineral absorption features and decomposes a synthetic mixture using reflectance spectra from the USGS Spectral Library Version 7 (splib07a).

The ASCII data archive `ASCIIdata_splib07a.zip` is available from USGS ScienceBase (item `586e8c88e4b0f5ce109fccae`). It contains one-reflectance-value-per-line text files organized by chapter, with bad bands flagged as `-1.23e34` and separate wavelength files per spectrometer. Use the ASD spectrometer measurements (0.35–2.5 µm, ~2151 channels).

From the minerals chapter, obtain ASD absolute-reflectance spectra for **Alunite**, **Calcite**, **Kaolinite** (well-ordered variant preferred), **Montmorillonite**, and **Muscovite**. For the 1.0–2.5 µm SWIR window, remove the spectral continuum from each spectrum and extract all absorption features with depth > 0.02, reporting center wavelength (µm), depth, FWHM (µm), and integrated area. Construct a synthetic mixture from Kaolinite (0.6) and Montmorillonite (0.4) on their shared valid-band grid with Gaussian noise (σ = 0.005, seed 42), then identify the two constituent minerals and estimate their mixing fractions.

## Required output (`/app/output/`)

- `absorption_features.json` — dict keyed by mineral identifier string (must contain the mineral name); each value is a list of feature dicts with keys `center_um`, `depth`, `fwhm_um`, `area`.
- `continuum_removed/<mineral_id>.csv` — two-column CSV (`wavelength_um`, `cr_reflectance`) for the 1.0–2.5 µm range, one per mineral.
- `mixture_identification.json` — dict with keys:
  - `identified_minerals`: list of 2 mineral identifier strings, ordered by spectral similarity to the mixture (most similar first)
  - `spectral_angles`: dict mapping each of the 5 mineral identifiers to the angle (radians) between the mixture and library spectrum vectors
  - `mixing_proportions`: dict mapping the 2 identified minerals to their estimated fraction