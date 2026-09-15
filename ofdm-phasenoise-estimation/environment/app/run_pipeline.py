#!/usr/bin/env python3
"""Run the OFDM processing pipeline on all captures and write results.json."""

import json
import numpy as np

from framework.ofdm_demod import remove_cp, fft_demod, extract_active
from framework.channel_est import estimate_channel
from framework.equalizer import zf_equalize
from framework.phase_noise import estimate_cpe, compensate_cpe, estimate_pn_bandwidth
from framework.metrics import compute_evm_db


def _pilot_indices(config):
    return list(range(0, config["n_active"], config["pilot_spacing"]))


def process_capture(capture_path, config):
    """Process a single OFDM capture through the full receiver chain."""
    rx_stream = np.load(capture_path)

    pilots = _pilot_indices(config)
    pilot_val = config["pilot_value_real"] + 1j * config["pilot_value_imag"]

    # Demodulate
    rx_time = remove_cp(rx_stream, config["n_fft"], config["n_cp"],
                        config["n_symbols"])
    rx_freq = fft_demod(rx_time)
    rx_active = extract_active(rx_freq, config["active_subcarrier_start"],
                               config["active_subcarrier_end"])

    # Channel estimation & equalization
    H_est = estimate_channel(rx_active, pilots, pilot_val)
    rx_eq = zf_equalize(rx_active, H_est)

    # EVM before CPE compensation
    evm_before = compute_evm_db(rx_eq, config["modulation"], pilots)

    # Phase noise processing
    cpe = estimate_cpe(rx_eq, pilots, pilot_val)
    rx_comp = compensate_cpe(rx_eq, cpe)
    evm_after = compute_evm_db(rx_comp, config["modulation"], pilots)
    f_3dB = estimate_pn_bandwidth(cpe, config)

    return {
        "evm_before_cpe_db": round(float(evm_before), 2),
        "evm_after_cpe_db": round(float(evm_after), 2),
        "estimated_pn_bandwidth_hz": round(float(f_3dB), 1),
    }


def main():
    with open("/app/config.json") as f:
        config = json.load(f)

    results = {}
    for i in range(config["n_captures"]):
        path = f"/app/captures/capture_{i}.npy"
        print(f"Processing {path} ...")
        res = process_capture(path, config)
        results[f"capture_{i}"] = res
        print(f"  EVM before CPE comp : {res['evm_before_cpe_db']:.2f} dB")
        print(f"  EVM after CPE comp  : {res['evm_after_cpe_db']:.2f} dB")
        print(f"  Est. PN bandwidth   : {res['estimated_pn_bandwidth_hz']:.1f} Hz")

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
