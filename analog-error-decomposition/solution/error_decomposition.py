
"""Error decomposition for HfO2 Bilayer RRAM analog MVM.

Computes NRMSE under different error scenarios, identifies the dominant
error source, and sweeps cell_bits / ADC bits to find the minimum
configuration meeting NRMSE < 0.05 with all errors at t=30 days.
"""

import sys
sys.path.insert(0, "/app")

import json
import numpy as np

# Register the custom device model before CrossSim discovers subclasses
from hfo2_rram import HfO2BilayerRRAM  # noqa: F401
from simulator import AnalogCore, CrossSimParameters


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
N = 64
RMIN = 5e3       # 5 kOhm
RMAX = 500e3     # 500 kOhm
BASE_CELL_BITS = 6
BASE_ADC_BITS = 8
NRMSE_TARGET = 0.05
SEED_BASE = 42
DEVICE_NAME = "HfO2BilayerRRAM"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def make_params(prog=False, noise=False, drift=False, drift_time=0,
                cell_bits=BASE_CELL_BITS, adc_bits=BASE_ADC_BITS):
    """Create CrossSimParameters for a balanced core with optional errors."""
    params = CrossSimParameters()
    params.core.style = "BALANCED"
    params.xbar.device.Rmin = RMIN
    params.xbar.device.Rmax = RMAX
    params.xbar.device.cell_bits = cell_bits

    if adc_bits > 0:
        params.xbar.adc.mvm.bits = adc_bits
        params.xbar.adc.mvm.model = "SignMagnitudeADC"
        params.xbar.adc.mvm.signed = True
        params.xbar.adc.mvm.adc_range_option = "MAX"

    if prog:
        params.xbar.device.programming_error.enable = True
        params.xbar.device.programming_error.model = DEVICE_NAME
    if noise:
        params.xbar.device.read_noise.enable = True
        params.xbar.device.read_noise.model = DEVICE_NAME
    if drift:
        params.xbar.device.drift_error.enable = True
        params.xbar.device.drift_error.model = DEVICE_NAME
        params.xbar.device.time = drift_time

    return params


def compute_nrmse(W, x, y_ideal, params, n_trials=50, seed=SEED_BASE):
    """Run n_trials MVMs and return the mean NRMSE."""
    nrmse_vals = []
    for i in range(n_trials):
        np.random.seed(seed + i)
        core = AnalogCore(W, params=params)
        y = np.asarray(core.matvec(x), dtype=np.float64)
        err = np.sqrt(np.mean((y - y_ideal) ** 2))
        ref = np.sqrt(np.mean(y_ideal ** 2))
        nrmse_vals.append(err / ref if ref > 0 else 0.0)
    return float(np.mean(nrmse_vals))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    # Weight matrix (deterministic via fixed seed)
    W = np.random.RandomState(123).randn(N, N)

    # Sinusoidal input
    t = np.arange(N, dtype=np.float64)
    x = np.sin(2.0 * np.pi * 3.0 * t / N) + 0.5 * np.cos(2.0 * np.pi * 7.0 * t / N)

    # Ideal (digital) output
    y_ideal = W @ x

    # --- 1. Error decomposition -------------------------------------------
    print("=== Error Decomposition ===")
    scenario_defs = {
        "quantization_only": dict(),
        "programming_error": dict(prog=True),
        "read_noise":        dict(noise=True),
        "drift_30d":         dict(drift=True, drift_time=30),
        "all_combined":      dict(prog=True, noise=True, drift=True, drift_time=30),
    }

    decomposition = {}
    for name, kw in scenario_defs.items():
        params = make_params(**kw)
        trials = 1 if name == "quantization_only" else 50
        nrmse = compute_nrmse(W, x, y_ideal, params, n_trials=trials)
        decomposition[name] = nrmse
        print(f"  {name:25s}  NRMSE = {nrmse:.6f}")

    # Dominant individual error source
    individual = {k: decomposition[k]
                  for k in ("programming_error", "read_noise", "drift_30d")}
    dominant = max(individual, key=individual.get)
    print(f"\n  Dominant error source: {dominant}")

    # --- 2. Cell-bits sweep -----------------------------------------------
    print("\n=== Cell-bits sweep (all errors, t=30d) ===")
    optimal_cell_bits = 10  # fallback
    for cb in range(2, 11):
        params = make_params(prog=True, noise=True, drift=True,
                             drift_time=30, cell_bits=cb)
        nrmse = compute_nrmse(W, x, y_ideal, params, n_trials=30)
        print(f"  cell_bits={cb:2d}  NRMSE = {nrmse:.6f}")
        if nrmse < NRMSE_TARGET:
            optimal_cell_bits = cb
            break

    # --- 3. ADC-bits sweep ------------------------------------------------
    print(f"\n=== ADC-bits sweep (cell_bits={optimal_cell_bits}, all errors, t=30d) ===")
    optimal_adc_bits = 16  # fallback
    for ab in (4, 6, 8, 10, 12, 14, 16):
        params = make_params(prog=True, noise=True, drift=True,
                             drift_time=30,
                             cell_bits=optimal_cell_bits, adc_bits=ab)
        nrmse = compute_nrmse(W, x, y_ideal, params, n_trials=30)
        print(f"  adc_bits={ab:2d}  NRMSE = {nrmse:.6f}")
        if nrmse < NRMSE_TARGET:
            optimal_adc_bits = ab
            break

    # --- 4. Write results -------------------------------------------------
    results = {
        "error_decomposition": decomposition,
        "dominant_error_source": dominant,
        "optimal_cell_bits": optimal_cell_bits,
        "optimal_adc_bits": optimal_adc_bits,
    }

    out_path = "/app/results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
