A partial QCM-D (Quartz Crystal Microbalance with Dissipation) analysis system exists at `/app/`. It is intended to compute complex frequency shifts (Δf and ΔΓ) for layered viscoelastic material stacks on a 5 MHz AT-cut quartz crystal resonator at odd overtones of the fundamental. The current implementation has defects in both the C library and the Python module, and is missing several required components.

Correct all defects and complete the system so it satisfies the validation data at `/app/reference_data.json` and the interface contracts below.

**C shared library:** `/app/qcm_transfer.c` compiled to `/app/libqcm_transfer.so` via `/app/Makefile` (`make all` / `make clean`). Exported symbol:

    void qcm_delfstar(int n, int nlayers, const double *grho3, const double *phi_deg,
                       const double *drho, double f1, double zq,
                       double *out_delf, double *out_delg)

Computes Δf (`out_delf`) and ΔΓ (`out_delg`) at overtone `n` for `nlayers` layers. Arrays ordered from crystal-adjacent (position 1) to outermost (position N). `drho > 1e100` denotes semi-infinite medium.

**Python module:** `/app/qcm_analysis.py` loading `libqcm_transfer.so` via `ctypes`. Constants: `Zq = 8.84e6`, `f1 = 5e6`. Required functions:

- `sauerbrey_mass(n, delf) -> float` (kg/m²)
- `grho(n, grho3, phi) -> float`
- `zstar_bulk(n, grho3, phi) -> complex`
- `calc_delfstar(n, layers) -> complex` (real=Δf, imag=ΔΓ)
- `solve_inverse(delfstar_expt, harmonics_f, harmonics_g, layers_init) -> dict` returning `{"grho3", "phi", "drho"}` for layer 1. Bounds: grho3∈[1e4,1e13], phi∈[0,90], drho∈[0,0.03].
- `compute_sensitivity(n, layers, param_name, layer_idx=1) -> complex`

Layer format: `dict[int, {"grho3": float, "phi": float, "drho": float}]` keyed by position (1=nearest crystal). `drho=float('inf')` = semi-infinite. Must handle 1- through 3+-layer stacks.

**CLI:** `/app/qcm_cli.py` — `python3 /app/qcm_cli.py --input <path> --output <path>`

- Forward: `{"mode":"forward","harmonics":[...],"layers":{"1":{...},...}}` → `{"delfstar":{"3":[re,im],...}}`
- Inverse: `{"mode":"inverse","layers":{...},"delfstar_expt":{"3":[re,im],...},"harmonics_f":[...],"harmonics_g":[...]}` → `{"solution":{"grho3":...,"phi":...,"drho":...},"residual_hz":float}`

JSON `drho > 1e100` = semi-infinite.

**Criteria:** Forward results within tolerances specified in `/app/reference_data.json`. Inverse round-trip residual < 1 Hz.
