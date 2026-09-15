The `tqec` Python package (v0.2.0) is pre-installed. It provides design automation for fault-tolerant surface code quantum computing via lattice surgery.

Produce `/app/analysis.json` containing three sections. Unless noted otherwise, use uniform depolarizing noise at physical error rate p=0.001.

## 1. "scaling"

For the gallery computations `memory`, `cnot`, and `three_cnots` (each configured for Z-basis observables), determine the compiled noisy circuit properties at code distances d=3, d=5, and d=7.

For each (computation, distance) pair, report:
- `num_qubits`, `num_detectors`, `num_observables`
- `num_error_mechanisms` — number of independent error entries in the fully decomposed detector error model
- `effective_code_distance` — minimum number of simultaneous physical errors needed to cause a logical failure (consider only graphlike error mechanisms)

## 2. "noise_comparison"

For the memory computation at d=5, compare the circuit's error structure under two noise models:

**"uniform"**: the standard uniform depolarizing model at p=0.001.

**"custom"**: an asymmetric noise model with these physical error characteristics:
- Idle qubit depolarization rate: 0.0002
- Single-qubit Clifford gate depolarization: 0.001
- Two-qubit Clifford gate depolarization: 0.005
- Measurement result flip probability: 0.003 (applies to every measurement basis the circuit uses)
- Reset error probability: 0.002 (X error after Z-basis resets, Z error after X-basis resets, X error after Y-basis resets)

For each noise model, report the five circuit metrics from section 1, plus:
- `logical_error_mechanisms` — error entries that flip at least one logical observable target
- `pure_detector_errors` — error entries that flip only detector targets
- `avg_detectors_per_mechanism` — mean detector target count per error entry (float, 6 decimal places)

## 3. "custom_memory"

Without using any gallery function, construct a block graph from scratch that implements a Z-basis logical memory experiment. Compile it at d=3, d=5, d=7 and report the same five metrics as section 1. A correct construction yields circuit metrics identical to the gallery memory version.

## Output schema

```json
{
  "scaling": {
    "<name>": {
      "d3": {"num_qubits": int, "num_detectors": int, "num_observables": int, "num_error_mechanisms": int, "effective_code_distance": int},
      "d5": {"...": "..."}, "d7": {"...": "..."}
    }
  },
  "noise_comparison": {
    "uniform": {
      "num_qubits": int, "num_detectors": int, "num_observables": int,
      "num_error_mechanisms": int, "effective_code_distance": int,
      "logical_error_mechanisms": int, "pure_detector_errors": int,
      "avg_detectors_per_mechanism": float
    },
    "custom": {"...": "..."}
  },
  "custom_memory": {
    "d3": {"...": "..."}, "d5": {"...": "..."}, "d7": {"...": "..."}
  }
}
```

All values are integers except `avg_detectors_per_mechanism` (float).