#!/usr/bin/env python3
"""OFDM demodulator: reads binary IQ captures, performs FFT, channel estimation, equalization.
Writes equalized data subcarrier complex values to intermediate text files."""
import numpy as np
import json
import os


def main():
    with open('/app/captures/manifest.json') as f:
        manifest = json.load(f)

    lts_ref_fftshift = np.array(manifest['lts_reference_fftshift'], dtype=np.complex128)
    data_idx = manifest['data_subcarrier_indices_fftshift']

    # Convert LTS reference to natural FFT order
    lts_ref_natural = np.fft.ifftshift(lts_ref_fftshift)

    os.makedirs('/app/demod', exist_ok=True)

    for frame_id in range(5):
        frame_key = f'frame_{frame_id}'
        frame_info = manifest['frames'][frame_key]
        filename = f"/app/captures/{frame_info['file']}"
        n_data_sym = frame_info['n_data_symbols']

        # Read binary IQ (interleaved float32: I0 Q0 I1 Q1 ...)
        raw = np.fromfile(filename, dtype=np.float32)
        iq = raw[0::2] + 1j * raw[1::2]

        # Parse structure: LTS1(64) + LTS2(64) + SIGNAL(64) + DATA_0(64) + ...
        lts1 = iq[0:64]
        lts2 = iq[64:128]

        # Channel estimation from LTS
        LTS1 = np.fft.fft(lts1)
        LTS2 = np.fft.fft(lts2)
        LTS_avg = (LTS1 + LTS2) / 2.0

        H = np.ones(64, dtype=np.complex128)
        for k in range(64):
            if lts_ref_natural[k] != 0:
                H[k] = LTS_avg[k] / lts_ref_natural[k]

        # Process SIGNAL + DATA symbols
        with open(f'/app/demod/frame_{frame_id}.txt', 'w') as out:
            n_total_sym = 1 + n_data_sym  # SIGNAL + DATA
            for sym_idx in range(n_total_sym):
                start = 128 + sym_idx * 64
                sym_time = iq[start:start + 64]

                # FFT to frequency domain
                sym_freq = np.fft.fft(sym_time)

                # Equalize
                sym_eq = sym_freq / H

                # Convert to fftshift order for subcarrier extraction
                sym_fftshift = np.fft.fftshift(sym_eq)

                # Extract data subcarriers
                data_vals = [sym_fftshift[i] for i in data_idx]

                # Write as space-separated real/imag pairs
                parts = []
                for z in data_vals:
                    parts.append(f"{z.real:.12f}")
                    parts.append(f"{z.imag:.12f}")
                out.write(' '.join(parts) + '\n')

        print(f"Frame {frame_id}: demodulated {n_total_sym} symbols ({n_data_sym} data)")


if __name__ == '__main__':
    main()
