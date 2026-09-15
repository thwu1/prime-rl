# Required Module Interfaces

All modules must be importable from `/app/src/`.

## phase_noise.py

### generate_phase_noise(psd_breakpoints, num_samples, sample_rate, seed)
Generate a time-domain phase noise signal (in radians) whose power spectral density matches the target PSD specification.
- **psd_breakpoints**: list of `[offset_frequency_hz, level_dBc_per_Hz]` pairs
- **num_samples**: int — number of output samples
- **sample_rate**: float — sampling rate in Hz
- **seed**: int or None — random seed for reproducibility
- **Returns**: numpy float array of shape `(num_samples,)`

In the full analysis, phase noise must be generated as a single continuous realization per trial spanning all OFDM symbols in the slot (not independently per symbol).

### measure_psd(signal, sample_rate, nperseg=None)
Measure the power spectral density of a signal.
- **signal**: 1D numpy array
- **sample_rate**: float (Hz)
- **nperseg**: optional int — segment length
- **Returns**: `(freqs, psd_dB)` — frequency vector (Hz) and PSD in dBc/Hz

## ofdm.py

### get_constellation(modulation)
Return the normalized QAM constellation with unit average power.
- **modulation**: str — one of `"QPSK"`, `"16QAM"`, `"64QAM"`
- **Returns**: 1D complex numpy array of constellation points

### get_subcarrier_allocation(n_fft, n_active, pilot_spacing)
Determine data and pilot subcarrier FFT bin indices. Active subcarriers are centered around DC (DC subcarrier is null). Pilots are placed at every `pilot_spacing`-th active subcarrier.
- **Returns**: `(data_indices, pilot_indices, active_sc)` where indices are FFT bin numbers

### ofdm_modulate(data_symbols, pilot_value, n_fft, data_indices, pilot_indices, cp_length)
Map data and pilot symbols to subcarriers and produce a time-domain OFDM symbol with cyclic prefix.
- **Returns**: `(tx_time_signal, freq_domain_symbol)`

Modulation followed by demodulation (without any channel impairment) must be lossless.

### ofdm_demodulate(rx_signal, n_fft, cp_length, data_indices, pilot_indices)
Remove cyclic prefix, transform to frequency domain, and extract data and pilot symbols.
- **Returns**: `(data_symbols, pilot_symbols, freq_domain_symbol)`

## evm_analyzer.py

### compute_evm(tx_symbols, rx_symbols)
Compute Error Vector Magnitude defined as RMS(error) / RMS(reference).
- **Returns**: `(evm_linear, evm_percent, evm_dB)`

### estimate_cpe(rx_pilots, tx_pilots)
Estimate Common Phase Error from pilot subcarrier observations.
- **rx_pilots**: received pilot symbols (1D complex array)
- **tx_pilots**: transmitted pilot symbols (1D complex array)
- **Returns**: CPE estimate in radians (float)

### correct_cpe(rx_symbols, cpe_rad)
Apply CPE correction to received symbols.
- **Returns**: corrected complex symbol array
