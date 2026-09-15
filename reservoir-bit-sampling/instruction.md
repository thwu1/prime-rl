The streaming data processor at `/app/` uses a reservoir sampler to select one element uniformly at random from a data stream of unknown length. The system consists of:

- A C library (`bitpool.c`, `bitpool.h`) providing random bits via a deterministic PRNG, built with the provided `Makefile`
- A Python ctypes wrapper (`bitsource.py`) exposing the C library as a `BitSource` class
- A reservoir sampler (`sampler.py`) implementing the `StreamSampler` class
- A diagnostic harness (`harness.py`) for testing the sampler's statistical properties

Two issues have been reported:

1. **Selection bias**: The sampler does not produce a uniform distribution over stream elements. Some items are selected significantly more often than others.
2. **Excessive entropy**: The sampler consumes far more random bits than necessary. For a stream of n elements, the total number of bits consumed should grow sublinearly with n.

Fix the system so that:

- Each of n elements has probability exactly 1/n of being selected, for any stream length n
- The average number of random bits consumed grows sublinearly in n
- All probability calculations are exact (no floating-point rounding errors may influence the outcome)
- The `StreamSampler` class in `/app/sampler.py` maintains its interface: `__init__(self, bit_source)`, `process(self, item)`, `result(self)`, `bits_used(self)`
- The sampler handles streams of up to 2000 elements within the time limit