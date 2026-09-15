Create `/app/tidal_engine.py` — a standalone Python module that predicts ocean tides from harmonic constituents. Your implementation must reproduce the behavior of pyTMD's OTIS-type correction model for all supported constituents. A validation oracle at `/app/validation_oracle.py` can generate reference outputs for debugging (requires pyTMD: `pip3 install pyTMD`). Your module must use only `numpy` and must not import or wrap pyTMD.

**Required API:**

`mean_longitudes(mjd)` — Five principal astronomical mean longitudes from Modified Julian Date. Returns `(s, h, p, n, ps)` in degrees, each normalized to [0, 360). Accepts scalar or array.

`equilibrium_arguments(mjd, constituents, corrections='OTIS')` — Equilibrium tidal arguments in degrees, shape `(nt, nc)`. Must support all 60 standard constituents: sa, ssa, mm, msf, mf, mt, alpha1, 2q1, sigma1, q1, rho1, o1, tau1, m1, chi1, pi1, p1, s1, k1, psi1, phi1, theta1, j1, oo1, 2n2, mu2, n2, nu2, m2a, m2, m2b, lambda2, l2, t2, s2, r2, k2, eta2, mns2, 2sm2, m3, mk3, s3, mn4, m4, ms4, mk4, s4, s5, m6, s6, s7, s8, m8, mks2, msqm, mtm, n4, eps2, z0 — plus variants m1b and l2b. Shallow-water constituents derive from combinations of parent constituents.

`nodal_corrections(mjd, constituents, corrections='OTIS')` — Nodal modulation phase and amplitude corrections. Returns `(pu, pf)`: phase in radians, amplitude factors dimensionless, both shape `(nt, nc)`. All amplitude factors must be strictly positive. Compound constituents inherit corrections from their parents.

`predict_tide(times_mjd, hc_real, hc_imag, constituents, corrections='OTIS')` — Predict tidal elevation from complex harmonic constants (1-D, length nc). Returns 1-D array length nt.

`infer_minor(times_mjd, hc_real, hc_imag, major_constituents, corrections='OTIS')` — Infer tidal contributions of minor constituents from major harmonic constants. Returns 1-D, length nt. Skips minors already in the major list. Returns zeros if fewer than 6 required majors available.

Constituent names are case-insensitive.
