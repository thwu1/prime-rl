# Elliptic Filter Design Module

This project requires a from-scratch implementation of analog elliptic (Cauer)
lowpass filter design in `elliptic_filter.py`, plus Bode magnitude plots
generated via gnuplot.

## Project structure

- `elliptic_filter.py` — Module stub with required API (implement this)
- `reference_data/` — JSON files with expected filter outputs for validation
- `tools/validate.py` — Local validation script
- `tools/filterspec.py` — Filter specification, analysis, and plotting CLI tool
- `output/` — Generated Bode plot SVGs (created by pipeline)
- `Makefile` — Build/validation targets

## Quick start

    make full-pipeline   # Run everything: check-deps -> validate -> bode
    make validate        # Run local validation against reference data
    make check-deps      # Verify no forbidden imports
    make bode            # Generate Bode plots via filterspec + gnuplot

## Using filterspec.py

    python3 tools/filterspec.py --help
    python3 tools/filterspec.py analyze reference_data/order5_rp1.0_rs40.json
    python3 tools/filterspec.py export-zpk 5 1.0 40.0 --output output/test.zpk
    python3 tools/filterspec.py bode-script output/test.zpk --output output/test.gp
    gnuplot output/test.gp
    python3 tools/filterspec.py pipeline --configs reference_data/ --output output/

## Constraints

The implementation in `elliptic_filter.py` must NOT import or use:
- `scipy.signal`, `scipy.special`, or `mpmath`
- Any library providing elliptic functions, integrals, or filter design

Only `numpy` (basic array/complex math) and the Python standard library are allowed.

## Reference data

The `reference_data/` directory contains JSON files with expected outputs for
several filter configurations. Each file includes poles, zeros, gain, and
frequency response samples. Use these to validate your implementation during
development.

## Accuracy targets

- Elliptic integral K(k): relative error < 1e-10 vs. reference
- Elliptic functions cd, sn: absolute error < 1e-10 vs. reference
- Inverse functions: round-trip error < 1e-8
- Filter poles/zeros: absolute error < 1e-4 vs. reference
- Filter gain: relative error < 1e-3 vs. reference
- Frequency response must satisfy passband/stopband bounds
