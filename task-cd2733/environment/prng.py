"""
HardenedPRNG - Cryptographically hardened pseudorandom number generator.

Uses a Linear Congruential Generator as the internal state machine,
with configurable output whitening via iterative SHA-512 hashing to
prevent internal state recovery from observed outputs.

Security depends on whiten_rounds being set to a sufficient value
(recommended: >= 64). When whiten_rounds == 0, output whitening is
disabled and raw LCG state is exposed directly.
"""

import hashlib


class HardenedPRNG:

    def __init__(self, seed, multiplier, increment, modulus, whiten_rounds=64):
        """
        Initialize the PRNG.

        Args:
            seed: Initial LCG state.
            multiplier: LCG multiplier (a).
            increment: LCG increment (c).
            modulus: LCG modulus (n).
            whiten_rounds: Number of SHA-512 iterations for output whitening.
                           Set to 0 to disable whitening (INSECURE).
        """
        self._state = seed % modulus
        self._m = multiplier
        self._c = increment
        self._n = modulus
        self._rounds = whiten_rounds

    def _advance(self):
        """Advance the internal LCG: state = (m * state + c) mod n."""
        self._state = (self._state * self._m + self._c) % self._n

    def _whiten(self, value):
        """Apply iterative SHA-512 whitening to prevent state leakage."""
        data = value.to_bytes(66, 'big')
        for _ in range(self._rounds):
            data = hashlib.sha512(data).digest()
        return int.from_bytes(data, 'big')

    def generate(self):
        """
        Generate the next pseudorandom output.

        If whiten_rounds > 0, the output is derived from the internal state
        via iterative hashing (computationally hiding the state).
        If whiten_rounds == 0, the raw LCG state is returned directly.
        """
        self._advance()
        if self._rounds > 0:
            return self._whiten(self._state)
        return self._state
