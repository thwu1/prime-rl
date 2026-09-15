Implement the NASA DAIDALUS Well-Clear Volume (WCV) conflict detection algorithm by translating the PVS formal specifications in `/app/specs/` into executable Python code.

These PVS specifications define the mathematically verified algorithm for detecting well-clear separation violations between aircraft pairs in the RTCA DO-365 Detect and Avoid standard. The specifications use parameterized theories, higher-order functions (time variable functions passed as parameters), dependent types, and formal proof obligations.

Your implementation must:

1. Read encounter states from `/app/encounters.json` (relative position and velocity of aircraft pairs in aviation units)
2. Read the multi-level alerting configuration from `/app/config.json`
3. For each encounter, compute the modified tau time variable, instantaneous WCV status (horizontal, vertical, 3D), the time interval of 3D WCV violation, and the alerting level
4. Write results to `/app/results.json`

See `/app/FORMAT.md` for the exact input/output schema and field definitions.

Key PVS specifications to translate:
- `horizontal_WCV_taumod.pvs`: defines `taumod(s,v)` (modified tau time variable), `horizontal_WCV_taumod(s,v)` (instantaneous check), and `horizontal_WCV_taumod_interval(T,s,v)` (closed-form interval via quadratic `a=sqv(v), b=2*(s*v)+TAUMOD*sqv(v), c=sqv(s)+TAUMOD*(s*v)-sq(DTHR)`)
- `horizontal_WCV.pvs`: defines the parametric `horizontal_WCV(tvar)(s,v)` using `tcpa` and distance thresholds
- `vertical_WCV.pvs`: defines `vertical_WCV(sz,vz)` and `coalt_entry_exit` for vertical interval
- `WCV.pvs`: composes horizontal and vertical into 3D WCV with interval intersection
- `horizontal_RA.pvs`: defines the TCAS-II horizontal resolution advisory logic that `tau_mod_def` is derived from
- `time_to_violation.pvs`: defines the multi-level alerting logic (`alert_from_ttvs`)

The `tau_mod_def(s,v)` function referenced in `horizontal_WCV_taumod.pvs` is the TCAS-II modified tau: `(DMOD^2 - |s|^2) / (s . v)`. The `Delta[D](s,v)` discriminant is `D^2 * |v|^2 - (s.v)^2`. The `Theta_D[D](s,v,eps)` cylinder boundary time is `(-(s.v) + eps*sqrt(Delta)) / |v|^2`.