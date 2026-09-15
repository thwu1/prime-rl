"""Deterministic random number generator for simulation.

All randomness in the simulation MUST flow through this RNG so that
a fixed seed guarantees identical execution.  Using any other source
of randomness (e.g. the module-level ``random`` functions, ``os.urandom``,
``time.time``) breaks determinism.
"""

import random as _random


class DetRng:
    """Seeded PRNG wrapper.  Each simulation instance gets its own."""

    def __init__(self, seed: int):
        self._seed = seed
        self._impl = _random.Random(seed)

    @property
    def seed(self) -> int:
        return self._seed

    def random(self) -> float:
        return self._impl.random()

    def randint(self, a: int, b: int) -> int:
        return self._impl.randint(a, b)

    def uniform(self, a: float, b: float) -> float:
        return self._impl.uniform(a, b)

    def choice(self, seq):
        return self._impl.choice(seq)

    def shuffle(self, x: list) -> None:
        self._impl.shuffle(x)

    def gauss(self, mu: float, sigma: float) -> float:
        return self._impl.gauss(mu, sigma)
