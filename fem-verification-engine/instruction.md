Build a structural mechanics verification engine at `/app/fem_verify.py`. The engine reads benchmark problem specifications from `/app/benchmarks/*.json` and computes analytical or semi-analytical reference solutions.

Running `python3 /app/fem_verify.py` must read every `.json` file in `/app/benchmarks/`, compute all quantities listed in its `"outputs"` field, and write results to `/app/results.json`.

Five benchmark files are pre-populated in `/app/benchmarks/`:

`thick_cylinder.json` — Plane-strain thick-walled hollow cylinder subjected to internal pressure and a steady-state radial temperature gradient between inner and outer surfaces. Compute radial stress, hoop stress, and radial displacement at specified evaluation radii.

`piston_fluid.json` — Lowest coupled eigenfrequency of a rigid piston closing one end of a fluid-filled tube whose far end is a rigid wall. Output: frequency in Hz.

`foundation_buckling.json` — Critical axial buckling load and corresponding mode of a simply-supported beam resting on an elastic foundation. Outputs: minimum critical load (N) and the associated half-wave number.

`plasticity_cycle.json` — Uniaxial stress-strain response of an elastoplastic material with linear isotropic hardening subjected to a multi-segment strain history that includes tension, elastic unloading, and reverse plastic loading. Compute stress and accumulated equivalent plastic strain at each segment endpoint.

`composite_laminate.json` — Effective in-plane elastic constants and ply-level stresses of a symmetric multi-angle laminate under specified in-plane resultant forces. Given unidirectional ply properties, stacking sequence, ply thicknesses, and applied force resultants, compute laminate-level effective moduli, mid-plane strains, and stresses resolved into each designated ply's material coordinate system.

Results schema for `/app/results.json`:
```json
{
  "benchmarks": {
    "<name>": {"<quantity>": <float>, ...}
  }
}
```

Units: stress in MPa, displacement in meters, frequency in Hz, force in N, strain dimensionless. Quantity names must match each benchmark's `"outputs"` array exactly. The engine must not depend on external FEA software; use only the Python standard library and widely-available scientific computing libraries.
