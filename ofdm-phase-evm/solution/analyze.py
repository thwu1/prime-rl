import numpy as np
import json
import sys
import yaml

sys.path.insert(0, "/app/src")

from phase_noise import generate_phase_noise, measure_psd
from ofdm import get_constellation, get_subcarrier_allocation, ofdm_modulate, ofdm_demodulate
from evm_analyzer import compute_evm, estimate_cpe, correct_cpe


def run_analysis(config_path="/app/config.yaml"):
    with open(config_path) as f:
        config = yaml.safe_load(f)

    ofdm_cfg = config["ofdm"]
    pn_cfg = config["phase_noise"]
    analysis_cfg = config["analysis"]

    n_fft = ofdm_cfg["n_fft"]
    n_active = ofdm_cfg["n_active"]
    cp_length = ofdm_cfg["cp_length"]
    modulation = ofdm_cfg["modulation"]
    num_symbols = ofdm_cfg["num_symbols"]
    pilot_spacing = ofdm_cfg["pilot_spacing"]
    scs = ofdm_cfg["scs_hz"]

    sample_rate = n_fft * scs  # 1024 * 30000 = 30.72 MHz
    psd_breakpoints = pn_cfg["psd_breakpoints"]

    seed = analysis_cfg["seed"]
    num_trials = analysis_cfg["num_trials"]

    constellation = get_constellation(modulation)
    data_indices, pilot_indices, active_sc = get_subcarrier_allocation(
        n_fft, n_active, pilot_spacing
    )

    n_data = len(data_indices)
    n_pilots = len(pilot_indices)
    pilot_value = 1.0 + 0j

    rng = np.random.default_rng(seed)

    all_evm_no_corr = []
    all_evm_cpe_corr = []
    all_cpe_deg = []
    all_phase_noise_samples = []

    for trial in range(num_trials):
        # Generate continuous phase noise for entire slot
        total_samples = num_symbols * (n_fft + cp_length)
        pn_seed = seed + trial * 1000
        phase_noise = generate_phase_noise(
            psd_breakpoints, total_samples, sample_rate, seed=pn_seed
        )
        all_phase_noise_samples.append(phase_noise)

        trial_tx_data = []
        trial_rx_data_no_corr = []
        trial_rx_data_cpe_corr = []
        trial_cpe = []

        sample_offset = 0

        for sym_idx in range(num_symbols):
            # Generate random data symbols
            data_syms = constellation[rng.integers(0, len(constellation), n_data)]

            # Modulate
            tx_signal, tx_freq = ofdm_modulate(
                data_syms, pilot_value, n_fft, data_indices, pilot_indices, cp_length
            )

            # Apply phase noise (continuous segment)
            pn_segment = phase_noise[sample_offset : sample_offset + len(tx_signal)]
            rx_signal = tx_signal * np.exp(1j * pn_segment)
            sample_offset += len(tx_signal)

            # Demodulate
            rx_data, rx_pilots, rx_freq = ofdm_demodulate(
                rx_signal, n_fft, cp_length, data_indices, pilot_indices
            )

            # Estimate CPE from pilots
            tx_pilots = np.full(n_pilots, pilot_value)
            cpe = estimate_cpe(rx_pilots, tx_pilots)
            trial_cpe.append(np.abs(np.degrees(cpe)))

            # Store for EVM computation
            trial_tx_data.append(data_syms)
            trial_rx_data_no_corr.append(rx_data)

            # CPE correction
            rx_data_corrected = correct_cpe(rx_data, cpe)
            trial_rx_data_cpe_corr.append(rx_data_corrected)

        # Compute EVM for this trial
        tx_all = np.concatenate(trial_tx_data)
        rx_no_corr = np.concatenate(trial_rx_data_no_corr)
        rx_cpe_corr = np.concatenate(trial_rx_data_cpe_corr)

        _, evm_pct_no, _ = compute_evm(tx_all, rx_no_corr)
        _, evm_pct_corr, _ = compute_evm(tx_all, rx_cpe_corr)

        all_evm_no_corr.append(evm_pct_no)
        all_evm_cpe_corr.append(evm_pct_corr)
        all_cpe_deg.extend(trial_cpe)

    # Average results across trials
    evm_pct_no_corr = float(np.mean(all_evm_no_corr))
    evm_pct_cpe_corr = float(np.mean(all_evm_cpe_corr))
    evm_dB_no_corr = 20.0 * np.log10(evm_pct_no_corr / 100.0)
    evm_dB_cpe_corr = 20.0 * np.log10(evm_pct_cpe_corr / 100.0)

    # CPE/ICI variance decomposition
    evm2_total = (evm_pct_no_corr / 100.0) ** 2
    evm2_ici = (evm_pct_cpe_corr / 100.0) ** 2
    evm2_cpe = max(evm2_total - evm2_ici, 0.0)

    cpe_frac = evm2_cpe / evm2_total if evm2_total > 0 else 0.0
    ici_frac = evm2_ici / evm2_total if evm2_total > 0 else 0.0

    # Integrated phase noise (total variance in dBc)
    all_pn = np.concatenate(all_phase_noise_samples)
    pn_variance = np.var(all_pn)
    integrated_pn_dBc = 10.0 * np.log10(pn_variance + 1e-30)

    # PSD check at breakpoint frequencies
    pn_freqs, pn_psd_dB = measure_psd(all_pn, sample_rate)
    psd_check = {}
    for bp_f, bp_dB in psd_breakpoints:
        if bp_f < pn_freqs[-1]:
            idx = np.argmin(np.abs(pn_freqs - bp_f))
            psd_check[str(bp_f)] = float(pn_psd_dB[idx])

    results = {
        "evm_percent_no_correction": float(evm_pct_no_corr),
        "evm_percent_cpe_corrected": float(evm_pct_cpe_corr),
        "evm_db_no_correction": float(evm_dB_no_corr),
        "evm_db_cpe_corrected": float(evm_dB_cpe_corr),
        "cpe_variance_contribution": float(cpe_frac),
        "ici_variance_contribution": float(ici_frac),
        "integrated_phase_noise_dBc": float(integrated_pn_dBc),
        "mean_cpe_degrees": float(np.mean(all_cpe_deg)),
        "phase_noise_psd_check": psd_check,
    }

    output_file = config["output"]["file"]
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == "__main__":
    results = run_analysis()
    print(json.dumps(results, indent=2))
