The directory `/app/` contains an OFDM signal processing framework and five IQ capture files (`/app/captures/capture_0.npy` through `/app/captures/capture_4.npy`). Each capture is a 16-QAM OFDM signal (1024-point FFT, 600 active subcarriers, 72-sample cyclic prefix) corrupted by multipath fading, AWGN at 30 dB SNR, and free-running oscillator phase noise whose 3-dB bandwidth is unknown and different for each capture. The phase noise severity increases from capture 0 to capture 4.

The framework in `/app/framework/` provides working modules for OFDM demodulation, LS channel estimation, ZF equalization, and EVM measurement. The module `/app/framework/phase_noise.py` contains three skeleton functions that must be implemented:

- `estimate_cpe` — extract the Common Phase Error per OFDM symbol from pilot subcarriers
- `compensate_cpe` — remove the estimated CPE from all subcarriers
- `estimate_pn_bandwidth` — determine the 3-dB bandwidth (Hz) of the underlying Wiener phase noise process from the CPE sequence

A runner script `/app/run_pipeline.py` orchestrates all processing stages and writes the output file. System parameters are in `/app/config.json`.

Produce `/app/results.json` with this structure:

```json
{
  "capture_0": {
    "evm_before_cpe_db": <float>,
    "evm_after_cpe_db": <float>,
    "estimated_pn_bandwidth_hz": <float>
  },
  "capture_1": { ... },
  "capture_2": { ... },
  "capture_3": { ... },
  "capture_4": { ... }
}
```