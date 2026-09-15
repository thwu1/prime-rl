Build `/app/xrd_tool.py`, a powder X-ray diffraction pattern simulator and phase identification tool operating on CIF data in `/app/data/`.

**`simulate` subcommand:**

```
python3 /app/xrd_tool.py simulate <cif_file> --wavelength <Å> --two-theta-max <degrees> --output <path>
```

Parse the CIF file, expand the asymmetric unit using all symmetry operations defined in the file, compute the powder XRD pattern, and write JSON:

```json
{
  "cell": {"a": float, "b": float, "c": float, "alpha": float, "beta": float, "gamma": float},
  "volume": float,
  "space_group": "string",
  "num_atoms_asymmetric": int,
  "num_atoms_unit_cell": int,
  "peaks": [{"hkl": [h,k,l], "d_spacing": float, "two_theta": float, "intensity": float, "multiplicity": int}]
}
```

Peaks ascending by `two_theta`, intensities normalized (strongest = 100.0), omit peaks with normalized intensity < 0.1. Intensities must account for atomic scattering factors, site occupancies, displacement parameters (in whichever form the CIF provides), Lorentz-polarization correction, and powder multiplicity. D-spacings via general metric tensor. Equivalent positions deduplicated within fractional tolerance 0.01.

**`identify` subcommand:**

```
python3 /app/xrd_tool.py identify <observed.json> <cif_dir> --wavelength <Å> --output <path>
```

Input: `{"peaks": [{"two_theta": float, "intensity": float}, ...]}`. Simulate every `.cif` in `cif_dir`, rank by intensity-weighted position-match figure of merit in [0, 1] (1 = perfect). Output: `{"best_match": "filename.cif", "rankings": [{"file": "string", "score": float}]}`, sorted descending by score.

**`fetch` subcommand:**

```
python3 /app/xrd_tool.py fetch <cod_id> --output <path>
```

Download a CIF file from the Crystallography Open Database at `https://www.crystallography.net/cod/<cod_id>.cif` and save to the output path. Non-zero exit on HTTP or network error.

**Constraints:**

- No external crystallographic libraries (pymatgen, ase, PyCifRW, cctbx, diffpy, Dans_Diffraction). Standard library + numpy only.
- Handle all seven crystal systems (triclinic through cubic).
- Must parse and produce correct results for every CIF file in `/app/data/`.
- Merge symmetry-equivalent reflections sharing the same d-spacing.
