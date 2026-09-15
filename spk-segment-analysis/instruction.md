`/app/data/de432s.bsp` is a JPL Development Ephemeris in SPICE SPK binary format. A leapseconds kernel is at `/app/data/naif0012.tls`.

Perform a deep binary-level audit of how the Earth-Moon Barycenter (EMB) trajectory is stored in this ephemeris file. Demonstrate that you can independently reproduce the toolkit's state computations directly from the raw binary data — not through high-level ephemeris query functions. All positions use the J2000 inertial frame, Solar System Barycenter origin, no aberration corrections.

## Required outputs

**`/app/segment_metadata.json`** — Locate the EMB segment in the binary file and characterize its internal numerical representation by navigating the file's low-level container architecture. Report these properties of the segment's coefficient storage: `poly_degree` (int), `n_coeffs_per_component` (int), `rsize` (int), `intlen_seconds` (float), `n_records` (int), `init_epoch_et` (float, ephemeris seconds past J2000).

**`/app/manual_position.json`** — Compute the EMB position at epoch **2020-JAN-01 12:00:00 TDB** by extracting and evaluating the stored coefficients from the binary file without calling any state-query or ephemeris-evaluation functions. Report: `x_km`, `y_km`, `z_km` (floats, km).

**`/app/verification_error.txt`** — Euclidean distance (km) between your raw-binary position computation and the toolkit's own evaluation at the same epoch. Single floating-point number. A correct implementation yields an error near machine epsilon.

**`/app/chebyshev_accuracy.json`** — Fit Chebyshev polynomials of degrees 5, 10, 15, 20, 25 to the EMB trajectory sampled at 50 equally-spaced epochs over 2020-JAN-01 00:00 TDB through 2020-JUL-01 00:00 TDB. For each degree, report the maximum single-component position error (km) across 5000 equally-spaced test epochs spanning the same interval. JSON keys: `"5"`, `"10"`, `"15"`, `"20"`, `"25"`.

**`/app/hermite_emb.bsp`** + **`/app/hermite_max_error.txt`** — Construct a Hermite-interpolation SPK for the EMB over the same 6-month interval, sampled at 1-day intervals, polynomial degree 7. Measure the maximum 3D position error (km) vs. the reference ephemeris at 5000 test points and write the result to `/app/hermite_max_error.txt`.