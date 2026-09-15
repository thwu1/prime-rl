The `/app/` directory contains an analog elliptic (Cauer) lowpass filter design pipeline. A C shared library (`libelliptic`) handles core numerical routines (Landen sequence, complete elliptic integral K(k), Jacobian cd function), loaded via `ctypes` in `native_binding.py`. Python modules handle inverse cd, the elliptic rational function, and pole/zero extraction. The public interface is `elliptic_filter.py`.

The analog pipeline is non-functional — multiple bugs exist across the build system, C code, ctypes bindings, and Python modules. The corrected pipeline must produce poles, zeros, and gain matching `scipy.signal.ellip` to the tolerances in the test suite.

Beyond the analog prototype, the system has no digital filter capability. You must design and implement `/app/digitize.py` providing:

- `bilinear_zpk(z, p, k, fs)` — bilinear transform converting analog zeros/poles/gain to digital at sample rate `fs`. Map each analog pole/zero via `z_d = (2fs + s) / (2fs - s)`. Add zeros at z=−1 for degree matching. Compensate gain. Return `(z_d, p_d, k_d)`.

- `zpk_to_sos(z, p, k)` — decompose digital zpk into cascaded second-order sections. Return an (L,6) array with rows `[b0, b1, b2, 1, a1, a2]`. Pair each conjugate pole pair with the conjugate zero pair having nearest angular frequency. Order sections by increasing pole magnitude. Handle odd-order filters with a single real pole.

- `min_order_for_spec(passband_hz, stopband_hz, ripple_db, atten_db, fs)` — find the minimum elliptic filter order (2–15) whose digitized realization meets the passband ripple and stopband attenuation at the given sample rate. Prewarp both band-edge frequencies before analog prototype design, then verify the digital frequency response. Return `(order, achieved_ripple_db, achieved_atten_db)`.

Finally, run the minimum-order analysis for every scenario in `/app/scenarios.json` and write results to `/app/results.json` with the format `{"scenario_name": {"min_order": N, "ripple_db": X, "atten_db": Y}, ...}`.

`digitize.py` must use only `numpy` and the `/app/elliptic_filter.py` module — no `scipy`.