"""Deterministic discrete-event simulation framework.

Inspired by MadSim (https://github.com/madsim-rs/madsim), this package
provides a single-threaded, seeded simulation engine, a simulated network
with partition / clog primitives, and a deterministic PRNG wrapper.
"""

from .rng import DetRng
from .engine import SimEngine
from .network import Network
