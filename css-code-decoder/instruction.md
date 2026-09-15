You are given three CSS quantum error correcting codes in different formats and a set of syndrome decoding and simulation tasks. Build a pipeline that produces `/app/results.json` satisfying all requirements below.

## Input Files

- `/app/codes/steane.json`, `/app/codes/shor.json` — CSS codes with fields `n`, `k`, `d`, `Hx`, `Hz`, `Lx`, `Lz`
- `/app/codes/hamming15.stab` — Stabilizer generators for a CSS code in Pauli string format (one generator per line, `#`-prefixed lines are comments, generators of different Pauli types are interleaved). Derive the complete code specification `[n, k, d]` and all four matrices `Hx`, `Hz`, `Lx`, `Lz` from this file.
- `/app/tasks.json` — Decoding tasks (each with a code name, error type, and error vector) and simulation tasks (each with a code name, error type, error rate, trial count, and random seed)

## Decoding Requirements

For each decoding task, compute the syndrome from the error vector and the appropriate check matrix, then decode using two independent backends identified as `maxsat` and `bposd`:

- **`maxsat`**: Must produce provably minimum-weight corrections for all unweighted tasks. For weighted tasks (which include per-qubit error rates), must produce maximum-likelihood corrections that account for those rates. Required for all tasks.
- **`bposd`**: Must produce valid corrections that resolve the syndrome. Required for all non-weighted tasks only.

Each decoded correction must satisfy: the check matrix applied to the correction yields the same syndrome as the original error. A logical error occurs when the residual (error XOR correction) anticommutes with any logical operator.

## Simulation Requirements

Each simulation task specifies a code, error type, physical error rate `p`, trial count, and random seed. For each trial, sample an i.i.d. bit-flip error vector (each qubit flipped independently with probability `p`), decode with both backends, and track logical error occurrences. Report per-backend logical error counts and rates.

## Output

Write `/app/results.json`:

    {
      "code_params": {
        "hamming15": {"n": <int>, "k": <int>, "d": <int>,
                      "Hx": [[...]], "Hz": [[...]], "Lx": [[...]], "Lz": [[...]]}
      },
      "decoding_results": {
        "<task_id>": {
          "maxsat": {"correction": [...], "weight": <int>,
                     "is_logical_error": <bool>, "syndrome_resolved": <bool>},
          "bposd": {"correction": [...], "weight": <int>,
                    "is_logical_error": <bool>, "syndrome_resolved": <bool>}
        }
      },
      "simulation_results": {
        "<task_id>": {
          "error_rate": <float>, "num_trials": <int>,
          "maxsat_logical_error_rate": <float>, "maxsat_num_logical_errors": <int>,
          "bposd_logical_error_rate": <float>, "bposd_num_logical_errors": <int>
        }
      }
    }

For weighted tasks, omit the `bposd` key from the decoding result.