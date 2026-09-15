"""Simulated network with partitions, latency, and packet loss.

Models point-to-point message passing between numbered nodes.  Supports:

* Per-message latency drawn from a configurable uniform range using the
  simulation's deterministic RNG.
* **Network partitions** — ``partition(a, b)`` should isolate two nodes
  bidirectionally (analogous to MadSim's ``disconnect2`` / ``clog_link``
  called in both directions).
* **Node-level clogging** — ``clog(n)`` drops all traffic to/from *n*.
* **Packet loss** — configurable random drop rate.

Messages are delivered by scheduling a future event on the simulation
engine, so delivery is subject to the same deterministic ordering as
every other event.
"""

import random                        # stdlib random – see note in send()
from typing import Any, Callable, Dict, Set, Tuple


class Network:
    """Simulated network connecting nodes in the simulation."""

    def __init__(self, engine, rng, latency=(0.005, 0.050), loss_rate=0.0):
        self._engine = engine
        self._rng = rng               # deterministic RNG for the simulation
        self._latency = latency       # (min, max) delivery delay
        self._loss_rate = loss_rate
        self._handlers: Dict[int, Callable] = {}
        self._partitions: Set[Tuple[int, int]] = set()
        self._clogged: Set[int] = set()
        self._delivered = 0
        self._dropped = 0

    # -- node management ------------------------------------------------------

    def register(self, node_id: int, handler: Callable) -> None:
        """Register *handler(src, dst, payload)* for *node_id*."""
        self._handlers[node_id] = handler

    def unregister(self, node_id: int) -> None:
        self._handlers.pop(node_id, None)

    # -- sending --------------------------------------------------------------

    def send(self, src: int, dst: int, payload: Any, tag: str = "") -> None:
        """Send *payload* from *src* to *dst* with simulated delay."""
        if dst not in self._handlers:
            return
        if self.is_partitioned(src, dst):
            self._dropped += 1
            return
        if src in self._clogged or dst in self._clogged:
            self._dropped += 1
            return
        if self._rng.random() < self._loss_rate:
            self._dropped += 1
            return

        # Compute delivery delay.
        delay = random.uniform(*self._latency)

        def deliver():
            # Re-check at delivery time (partition state may have changed).
            if dst in self._handlers and not self.is_partitioned(src, dst):
                self._delivered += 1
                self._handlers[dst](src, dst, payload)
            else:
                self._dropped += 1

        self._engine.schedule(delay, deliver, tag=tag or f"msg:{src}->{dst}")

    # -- partition control ----------------------------------------------------

    def partition(self, a: int, b: int) -> None:
        """Create a network partition between *a* and *b*.

        This should prevent communication in BOTH directions: a→b and b→a.
        """
        self._partitions.add((a, b))

    def heal(self, a: int, b: int) -> None:
        """Remove the partition between *a* and *b*."""
        self._partitions.discard((a, b))

    def is_partitioned(self, src: int, dst: int) -> bool:
        """Return True when traffic from *src* to *dst* is blocked."""
        return (src, dst) in self._partitions

    # -- node-level clog ------------------------------------------------------

    def clog(self, node_id: int) -> None:
        """Drop ALL traffic to/from *node_id*."""
        self._clogged.add(node_id)

    def unclog(self, node_id: int) -> None:
        self._clogged.discard(node_id)

    # -- stats ----------------------------------------------------------------

    @property
    def stats(self) -> dict:
        return {"delivered": self._delivered, "dropped": self._dropped}
