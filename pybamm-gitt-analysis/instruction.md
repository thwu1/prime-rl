A prototype GITT (Galvanostatic Intermittent Titration Technique) analysis pipeline at `/app/gitt_pipeline.py` simulates an LGM50 lithium-ion cell (NMC/graphite, ~5 A.h nominal capacity) using PyBaMM with the Chen2020 parameter set. The pipeline runs without runtime errors but its protocol design choices and data extraction logic may violate fundamental electrochemical principles required for valid GITT measurements.

Critically evaluate the pipeline's C-rate selection, experiment structure, and resistance computation against established GITT methodology. A valid GITT protocol requires perturbation currents small enough to maintain quasi-equilibrium conditions and rest periods between pulses to allow the cell voltage to relax back to thermodynamic equilibrium — the "Intermittent" in GITT. Additionally, compare `pybamm.lithium_ion.SPM()` (Single Particle Model) and `pybamm.lithium_ion.SPMe()` (Single Particle Model with electrolyte) for this GITT analysis: evaluate which model formulation more accurately captures the physics relevant to internal resistance extraction across the SOC range, and select the better one for your final results.

Produce a corrected 8-pulse GITT analysis using 300-second discharge pulses and write the output to `/app/results.json` with this schema:

```json
{
  "n_pulses": 8,
  "model_used": "<selected model: 'SPM' or 'SPMe'>",
  "pulses": [
    {
      "pulse_number": 1,
      "v_before_pulse": "<equilibrium OCV before discharge pulse [V]>",
      "v_end_pulse": "<terminal voltage at end of discharge pulse [V]>",
      "v_after_relaxation": "<relaxed OCV after rest period [V]>",
      "current_A": "<discharge current magnitude [A]>",
      "internal_resistance_ohm": "<(v_before_pulse - v_end_pulse) / current_A [ohm]>",
      "approx_soc": "<state of charge after pulse>"
    }
  ],
  "average_resistance_ohm": "<arithmetic mean of per-pulse internal_resistance_ohm [ohm]>",
  "resistance_trend": "<'increasing' or 'decreasing'>",
  "total_charge_removed_Ah": "<cumulative charge removed across all pulses [A.h]>"
}
```

## Physical Constraints

The corrected results must satisfy all of the following for an NMC/graphite cell:

- Exactly 8 pulses, numbered 1 through 8 sequentially.
- `model_used` must be `"SPM"` or `"SPMe"`.
- All voltages (`v_before_pulse`, `v_end_pulse`, `v_after_relaxation`) must lie in (2.0, 4.3) V.
- First pulse's `v_before_pulse` must be in (3.9, 4.3) V (near fully-charged OCV).
- `v_before_pulse` > `v_end_pulse` for every pulse (discharge lowers terminal voltage below equilibrium).
- `v_after_relaxation` > `v_end_pulse` for every pulse, with the recovery exceeding 20 mV (rest allows voltage to relax toward equilibrium).
- `v_after_relaxation` must decrease monotonically across successive pulses.
- All `internal_resistance_ohm` values must be positive and in [0.001, 0.5] ohm (1–500 mOhm).
- `average_resistance_ohm` must equal the arithmetic mean of per-pulse resistances within 0.1 mOhm.
- `resistance_trend` must be `"increasing"` or `"decreasing"`.
- Each pulse's `current_A` must be in (1.0, 3.0) A (appropriate C-rate for ~5 A.h cell under GITT).
- `total_charge_removed_Ah` must be in (0.5, 3.0) A.h and consistent with the sum of per-pulse charges (`current_A × 300 / 3600`) within 5%.
- `approx_soc` must be in [0, 1], decrease monotonically, with the first value > 0.9 and the last value in (0.5, 0.95).
- All numeric values must be finite.