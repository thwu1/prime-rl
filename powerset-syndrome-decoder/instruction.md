Build a syndrome decoder at `/app/decoder.py` that identifies the most probable error configuration consistent with an observed syndrome in a quantum error correction system.

## Problem

A Detector Error Model (DEM) specifies a set of independent error mechanisms. Each error has a probability, activates a subset of detectors, and may flip logical observables. Example DEMs are provided in `/app/dems/`. A syndrome is the set of detectors that activated during a round of error correction.

Given a syndrome, the decoder must find the error set that minimizes total cost while its combined detector activations match the observed syndrome. When multiple errors activate the same detector, the activations cancel (XOR / symmetric difference). The cost of an error with probability `p` is `-ln(p / (1 - p))`. The decoder must also report which logical observables are flipped by the identified errors (also combined via XOR).

## Interface

Implement the `SyndromeDecoder` class in `/app/decoder.py`. A skeleton with the required signature is already in place.

- `__init__(self, dem_text, beam_width=5, pq_limit=200000)`: Parse a DEM and prepare the decoder with the given configuration parameters.
- `decode(self, syndrome) -> dict`: Return `{'errors': list[int], 'observables': list[int], 'cost': float, 'low_confidence': bool}`. Error indices are 0-based in DEM order (counting only valid errors — those with at least one detector and `0 < p < 1`). Set `low_confidence=True` when the decoder cannot guarantee the returned solution is optimal.
- Properties: `num_errors`, `num_detectors`, `num_observables`.

## Success Criteria

- Finds optimal (minimum-cost) solutions on instances with up to 8 errors
- Produces correct, syndrome-consistent results on instances with 30–60+ error mechanisms within time limits
- Decoded errors' combined detector signature equals the input syndrome
- Predicted observable flips match the decoded error set
- Works with DEMs produced by `stim` from real quantum circuits (the `stim` package is available in the environment)