Build `/app/cdspec`, an executable Python script for circular dichroism (CD) spectroscopy analysis. Domain reference material describing CD conventions and analytical methods is at `/app/docs/`. Run `python3 /app/setup_data.py` to populate `/app/data/`.

Five subcommands are required:

**`cdspec convert --input FILE --from-unit UNIT --to-unit UNIT --conc FLOAT --mw FLOAT --nres INT --path FLOAT`**
Convert a two-column CSV (wavelength_nm, signal) between CD units: `mdeg` (millidegrees), `mre` (mean residue ellipticity), `de` (delta epsilon per residue). `--conc`: mg/mL, `--mw`: Da, `--nres`: residue count, `--path`: pathlength cm. Skip `#` comment lines. Output JSON: `{"wavelengths": [...], "values": [...]}`.

**`cdspec deconvolve --spectrum FILE --basis FILE`**
Estimate protein secondary structure fractions from a CD spectrum and reference basis spectra. Basis CSV columns: wavelength,helix,strand,turn,coil. Spectrum CSV columns: wavelength,delta_epsilon. Fractions must be biophysically valid. Handle mismatched wavelength grids. Output JSON: `{"fractions": {"helix":..., "strand":..., "turn":..., "coil":...}, "nrmsd":..., "reconstructed":[...]}`.

**`cdspec thermomelt --input FILE`**
Analyze thermal denaturation data (CSV: temperature_K, signal). The raw signal includes both the cooperative folding transition and temperature-dependent baseline contributions that must be accounted for. Output JSON: `{"tm_K":..., "dh_kj_mol":..., "fraction_folded":[...]}`.

**`cdspec validate --input FILE --metadata FILE`**
Assess CD measurement quality. The spectrum is a two-column CSV; metadata is a JSON file with instrument parameters. Implement the validation checks documented in `/app/docs/data_quality_validation.txt`. Overall pass requires all individual checks to pass. Output JSON: `{"passed": bool, "checks": {"check_name": {"passed": bool, "value":..., "threshold":...}, ...}}`.

**`cdspec match --query FILE --library DIR`**
Rank CSV files in a directory by spectral distance to a query spectrum. Interpolate to mutual wavelength overlap when ranges differ. Output JSON: `{"rankings": [{"file": "name.csv", "nrmsd":...}, ...]}` sorted ascending.

All numeric JSON values rounded to 4 decimal places. Exit 0 on success, non-zero with stderr on error.
