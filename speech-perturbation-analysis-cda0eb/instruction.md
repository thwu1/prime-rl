A reference speech feature extraction toolkit is at `/app/reference/`. It depends on external libraries (`pysptk`, `praat`, `kaldi_io`, `torch`, `pandas`, `matplotlib`, `tqdm`) that are **not installed**. Produce a working reimplementation at the paths below that matches the reference's numerical behavior, using only `scipy` and `numpy` (installable via pip).

**`/app/preprocess.sh`** (executable) — Audio normalizer using the pre-installed `sox` command. Usage: `bash /app/preprocess.sh <input.wav> <output.wav>`. Output must be 16 kHz, mono, 16-bit PCM WAV with sub-50 Hz content removed and peak-normalized amplitude.

**`/app/phonation.py`** — Must export functions whose behavior matches the reference's `phonation_functions.py` and `phonation.py`:

- `jitter_env(f0_voiced, n_points)` -> `ndarray` of length `n_points`
- `shimmer_env(amplitudes, n_points)` -> `ndarray` of length `n_points`
- `perturbation_quotient(x, k)` -> `float`
- `apq(amplitudes)` -> `float`
- `ppq(f0_values)` -> `float`
- `log_energy(frame)` -> `float`
- `extract_f0(wav_path)` -> `ndarray` per-frame F0 contour; 0 for unvoiced frames; valid non-zero values in [60, 350] Hz; must track time-varying pitch
- `extract_static(wav_path)` -> 28-element `ndarray`; all values finite; silence or insufficient voiced content -> 28 zeros
- `extract_dynamic(wav_path)` -> `(N, 7) ndarray`

**`/app/prosody.py`** — Must export functions whose behavior matches the reference's `prosody.py`:

- `extract_static(wav_path)` -> 103-element `ndarray`; all values finite
- `extract_dynamic(wav_path)` -> `(N, 13) ndarray`; all values finite; durations > 0

**`/app/extract.py`** — CLI tool. Usage: `python3 /app/extract.py <phonation|prosody> <static|dynamic> <wav_path>`. Must preprocess the input through `/app/preprocess.sh` before feature extraction. Outputs comma-separated float values to stdout (one line for static, N lines for dynamic). Must accept non-16 kHz and multichannel WAV inputs.

Both modules must independently handle stereo WAV files, silence, and very short signals (< 40 ms), always returning correctly-dimensioned finite arrays.
