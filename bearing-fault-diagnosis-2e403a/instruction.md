Build a Python package at `/app/bearing_diagnostics/` for vibration-based rolling-element bearing fault diagnosis. The package must be importable and expose three public functions via `__init__.py`.

**`compute_defect_frequencies(bearing_params, shaft_hz)`**

`bearing_params` is a dict with keys: `rd` (roller diameter), `pd` (pitch diameter), `ne` (int, number of rolling elements), `ca_deg` (contact angle in degrees), `outer_fixed` (bool, whether outer race is stationary). `shaft_hz` is shaft rotational frequency in Hz. Returns a dict with float keys `BPFO`, `BPFI`, `BSF`, `FTF` in Hz. Reference values for validation are in `/app/bearing_reference.json`. Note the BSF convention documented there. BPFO and BPFI do not depend on which race is fixed; only FTF does.

**`envelope_spectrum(signal, sample_rate, band_low, band_high, nperseg=None)`**

Accepts a 1-D vibration signal array, sample rate in Hz, and bandpass filter bounds in Hz. Returns `(frequencies, psd)` — two 1-D NumPy arrays representing the power spectral density of the demodulated envelope signal. When `nperseg` is `None`, use a reasonable default.

**`diagnose(signal, sample_rate, bearing_params, shaft_hz)`**

Full diagnostic pipeline. Given a raw vibration signal, bearing geometry, and shaft speed, determine what kind of fault (if any) is present. Returns a dict:

- `fault_type`: one of `"healthy"`, `"outer_race"`, `"inner_race"`, `"rolling_element"`
- `confidence`: float in [0, 1]
- `defect_frequencies`: dict with `BPFO`, `BPFI`, `BSF`, `FTF`
- `detected_peaks_hz`: list of floats (detected peak frequencies in Hz)
- `fault_frequency_hz`: float or `None` (dominant fault frequency)
- `severity`: float >= 0 (relative fault severity metric)

The `diagnose` function must handle signals at sample rates from 10 kHz to 100 kHz, different bearing geometries including non-zero contact angles, SNR levels down to 10 dB, and signals where the structural resonance frequency is unknown and varies across recordings.

The `severity` value must increase monotonically with fault intensity for a given fault type and bearing: stronger faults must produce strictly higher severity values when compared under identical noise conditions.
