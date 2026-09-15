
"""
Analog crossbar error budget decomposition and Pareto architecture design.
"""

import json
import math
import sys

import numpy as np
import scipy.linalg

from simulator import AnalogCore, CrossSimParameters

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DFT_SIZE = 64
WEIGHT_BITS = 8
INPUT_BITS = 8
NUM_INPUTS = 10
SEED_INPUTS = 42
SEED_CORE = 123

RMIN = 1000
RMAX = 100000
PROG_ALPHA = 0.05
NOISE_ALPHA = 0.03

NSLICES_OPTIONS = [1, 2, 4]
ADC_BITS_OPTIONS = [6, 8, 10]
WEIGHT_MAPPING_OPTIONS = ["BALANCED", "OFFSET"]
INPUT_SLICE_OPTIONS = [1, 2, 4, 8]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def compute_cost(ns, ab, wm, isl):
    M = 2 if wm == "BALANCED" else 1
    return ns * M * (2 ** ab) * int(math.ceil(INPUT_BITS / isl))


def compute_snr(y_analog, y_ideal):
    sp = np.sum(np.abs(y_ideal) ** 2)
    ep = np.sum(np.abs(y_analog - y_ideal) ** 2)
    if ep < 1e-30:
        return 100.0
    return 10.0 * np.log10(sp / ep)


def create_params(ns, ab, wm, isl, prog_en=True, noise_en=True):
    """Build CrossSimParameters for a given config and error toggles."""
    p = CrossSimParameters()

    p.core.complex_matrix = True
    p.core.complex_input = True
    p.core.weight_bits = WEIGHT_BITS
    p.core.rows_max = 128
    p.core.cols_max = 128
    p.core.mapping.weights.percentile = 1.0
    p.core.mapping.inputs.mvm.min = -1.0
    p.core.mapping.inputs.mvm.max = 1.0

    # Core style
    if ns == 1:
        p.core.style = wm
    else:
        p.core.style = "BITSLICED"
        p.core.bit_sliced.style = wm
        p.core.bit_sliced.num_slices = ns

    # Cell bits
    if wm == "BALANCED":
        cb = WEIGHT_BITS - 1 if ns == 1 else int(math.ceil((WEIGHT_BITS - 1) / ns))
    else:
        cb = WEIGHT_BITS if ns == 1 else int(math.ceil(WEIGHT_BITS / ns))
    p.xbar.device.cell_bits = cb

    # Device
    p.xbar.device.Rmin = RMIN
    p.xbar.device.Rmax = RMAX

    # Programming error (conditionally enabled)
    p.xbar.device.programming_error.enable = prog_en
    if prog_en:
        p.xbar.device.programming_error.model = "NormalProportionalDevice"
        p.xbar.device.programming_error.magnitude = PROG_ALPHA

    # Read noise (conditionally enabled)
    p.xbar.device.read_noise.enable = noise_en
    if noise_en:
        p.xbar.device.read_noise.model = "NormalIndependentDevice"
        p.xbar.device.read_noise.magnitude = NOISE_ALPHA

    # ADC
    p.xbar.adc.mvm.bits = ab
    p.xbar.adc.mvm.model = "SignMagnitudeADC"
    p.xbar.adc.mvm.signed = True
    p.xbar.adc.mvm.adc_range_option = "MAX"

    # DAC
    p.xbar.dac.mvm.bits = INPUT_BITS
    p.xbar.dac.mvm.model = "SignMagnitudeDAC"
    p.xbar.dac.mvm.signed = True
    if isl < INPUT_BITS:
        p.xbar.dac.mvm.input_bitslicing = True
        p.xbar.dac.mvm.slice_size = isl
    else:
        p.xbar.dac.mvm.input_bitslicing = False

    # Balanced / offset styles
    p.core.balanced.style = "ONE_SIDED"
    p.core.balanced.subtract_current_in_xbar = True
    p.core.offset.style = "DIGITAL_OFFSET"

    p.validate()
    return p


def simulate(cfg, W, ti, ideal, prog_en=True, noise_en=True):
    """Run CrossSim simulation and return mean SNR in dB."""
    np.random.seed(SEED_CORE)
    params = create_params(
        cfg["Nslices"], cfg["adc_bits"], cfg["weight_mapping"],
        cfg["input_slice_size"], prog_en=prog_en, noise_en=noise_en,
    )
    core = AnalogCore(W, params=params)
    snrs = [compute_snr(core @ ti[i], ideal[i]) for i in range(NUM_INPUTS)]
    return float(np.mean(snrs))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    # --- Generate test data ---
    W = scipy.linalg.dft(DFT_SIZE)
    np.random.seed(SEED_INPUTS)
    ti = (np.random.randn(NUM_INPUTS, DFT_SIZE)
          + 1j * np.random.randn(NUM_INPUTS, DFT_SIZE))
    ti /= np.max(np.abs(ti))
    ideal = np.array([W @ x for x in ti])

    ref = {"Nslices": 2, "adc_bits": 6,
           "weight_mapping": "OFFSET", "input_slice_size": 8}

    # ==== Error Source Attribution ====
    print("=== Error Source Attribution ===")

    baseline = simulate(ref, W, ti, ideal, prog_en=False, noise_en=False)
    prog_only = simulate(ref, W, ti, ideal, prog_en=True, noise_en=False)
    noise_only = simulate(ref, W, ti, ideal, prog_en=False, noise_en=True)
    all_err = simulate(ref, W, ti, ideal, prog_en=True, noise_en=True)

    dp = baseline - prog_only
    dn = baseline - noise_only
    dc = baseline - all_err
    interaction = dc - dp - dn
    dominant = "programming_error" if dp > dn else "read_noise"

    print(f"  Baseline (quant-only):  {baseline:.4f} dB")
    print(f"  Prog error only:       {prog_only:.4f} dB  (delta={dp:.4f})")
    print(f"  Read noise only:       {noise_only:.4f} dB  (delta={dn:.4f})")
    print(f"  All errors:            {all_err:.4f} dB  (delta={dc:.4f})")
    print(f"  Dominant source:       {dominant}")
    print(f"  Interaction delta:     {interaction:.6f} dB")

    # ==== Design Space Sweep ====
    print("\n=== Design Space Sweep ===")
    all_configs = []
    total = (len(NSLICES_OPTIONS) * len(ADC_BITS_OPTIONS)
             * len(WEIGHT_MAPPING_OPTIONS) * len(INPUT_SLICE_OPTIONS))
    done = 0

    for ns in NSLICES_OPTIONS:
        for ab in ADC_BITS_OPTIONS:
            for wm in WEIGHT_MAPPING_OPTIONS:
                for isl in INPUT_SLICE_OPTIONS:
                    done += 1
                    cost = compute_cost(ns, ab, wm, isl)
                    cfg = {"Nslices": ns, "adc_bits": ab,
                           "weight_mapping": wm, "input_slice_size": isl}
                    try:
                        snr = simulate(cfg, W, ti, ideal)
                        print(f"[{done}/{total}] ns={ns} ab={ab} wm={wm} "
                              f"isl={isl} cost={cost} SNR={snr:.2f}")
                        all_configs.append({
                            **cfg, "snr_db": round(snr, 4), "cost": cost})
                    except Exception as e:
                        print(f"[{done}/{total}] ERROR: {e}", file=sys.stderr)

    # ==== Pareto Frontier ====
    print("\n=== Pareto Frontier ===")
    pareto = []
    for c in all_configs:
        dominated = False
        for d in all_configs:
            if d is c:
                continue
            if (d["cost"] <= c["cost"] and d["snr_db"] >= c["snr_db"]
                    and (d["cost"] < c["cost"] or d["snr_db"] > c["snr_db"])):
                dominated = True
                break
        if not dominated:
            pareto.append(c)
    pareto.sort(key=lambda x: x["cost"])
    dominated_count = len(all_configs) - len(pareto)

    print(f"  Pareto-optimal: {len(pareto)} configs")
    print(f"  Dominated:      {dominated_count} configs")
    for p in pareto:
        print(f"    cost={p['cost']:6d}  SNR={p['snr_db']:.2f}  "
              f"ns={p['Nslices']} ab={p['adc_bits']} "
              f"wm={p['weight_mapping']} isl={p['input_slice_size']}")

    # ==== Best Efficiency ====
    print("\n=== Efficiency Recommendation ===")
    best = None
    for c in pareto:
        eff = c["snr_db"] / c["cost"]
        if best is None or eff > best["efficiency"]:
            best = {**c, "efficiency": eff}

    print(f"  Recommended: {best}")

    # ==== Write Output ====
    output = {
        "reference_analysis": {
            "baseline_snr": round(baseline, 4),
            "prog_error_only_snr": round(prog_only, 4),
            "read_noise_only_snr": round(noise_only, 4),
            "all_errors_snr": round(all_err, 4),
            "dominant_source": dominant,
            "interaction_delta_db": round(interaction, 4),
        },
        "pareto_frontier": pareto,
        "dominated_count": dominated_count,
        "recommended_config": best,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(output, f, indent=2)

    print("\nResults written to /app/analysis.json")


if __name__ == "__main__":
    main()
