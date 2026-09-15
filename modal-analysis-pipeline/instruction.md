Implement `/app/modal_analysis.py` exposing five functions for frequency-domain modal identification from measured FRFs. Only `numpy` and `scipy` are available as dependencies.

Run `/app/generate_frf.py` to produce `/app/data/frf_data.npz` (keys: `freq`, `frf`, `nat_freq_true`, `damping_true`, `mode_shapes_true`). The data represents accelerance FRFs from a 5-DOF damped mass-spring-damper system.

Required API — all functions must accept and return the types/shapes shown:

`identify_poles(frf, freq, lower, upper, pol_order_high)` — returns `{'all_poles': list[complex array], 'pole_freq': list[array], 'pole_xi': list[array]}`. One entry per even order in `[2, pol_order_high]`. Poles are complex; frequencies in Hz; damping ratios dimensionless.

`select_stable_poles(all_poles, pole_freq, pole_xi, approx_nat_freq, f_window=50)` — returns `{'nat_freq': array, 'nat_xi': array, 'selected_poles': complex array}`. Exactly one entry per element of `approx_nat_freq`.

`identify_modal_constants(poles, frf, freq, frf_type='receptance')` — returns `{'modal_constants': complex (n_loc, n_modes), 'reconstructed_frf': complex (same shape as frf), 'LR': complex (n_loc,), 'UR': complex (n_loc,)}`. Must support `frf_type` in `{'receptance', 'mobility', 'accelerance'}`.

`mac(phi_X, phi_A)` — returns real matrix with values in [0, 1]. Inputs are 1D or 2D `(n_loc, n_modes)`, possibly complex. For 1D inputs, return a scalar or `(1,1)` array.

`complex_to_normal_mode(mode)` — returns real array `(n_loc, n_modes)` from complex input of same shape.

Acceptance criteria:
- Identified natural frequencies within 1 Hz absolute or 2% relative of ground truth
- Identified damping ratios within 5% relative of ground truth
- Modal constants shape `(n_locations, n_modes)`
- FRF reconstruction relative magnitude error < 30% near each resonance (within +/-20 Hz) at DOFs with significant response
- AutoMAC diagonal entries equal 1.0; all values in [0, 1]; matrix symmetric
- Normal modes real-valued with MAC > 0.85 against original complex modes
