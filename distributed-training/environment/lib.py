"""
Distributed LLM Training Simulation Framework.

Simulates multi-GPU distributed training with communication primitives
(allreduce, allgather, scatter-reduce, point-to-point) using asyncio.
No actual GPU required - all operations are symbolic simulations that
track correctness, timing, and memory usage.

Requires cost_model.py to be generated from the native cost model tool:
  cd /app/native && make && ./cost_model_gen hw_spec.bin /app/cost_model.py
"""

from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import (Any, Dict, List, Optional, Protocol, Sequence,
                    Tuple, FrozenSet, TypeVar)

try:
    from cost_model import HIDDEN, LENGTH, COLLECTIVE_COST, P2P_COST, UPDATE_COST
except ImportError:
    raise ImportError(
        "cost_model.py not found. Build and run the cost model generator:\n"
        "  cd /app/native && make && ./cost_model_gen hw_spec.bin /app/cost_model.py"
    )


class Barrier:
    """Reusable async barrier for synchronizing n ranks."""
    def __init__(self, target: int):
        self.counter = 0
        self.target = target
        self.lock = asyncio.Lock()
        self.done = 0

    async def wait(self, rank: int) -> None:
        while self.done > 0:
            await asyncio.sleep(0.01)
        async with self.lock:
            self.counter += 1
        while self.counter < self.target:
            await asyncio.sleep(0.01)
        self.done += 1
        if rank == 0:
            await self._reset()

    async def _reset(self) -> None:
        while self.done < self.target:
            await asyncio.sleep(0.01)
        self.counter = 0
        self.done = 0


T = TypeVar('T')


class Reduceable(Protocol[T]):
    def __add__(self, other: T) -> T: ...


O = TypeVar('O')


class Gatherable(Protocol[O]):
    def shard(self, shard: int, total: int) -> O: ...
    def is_complete(self) -> bool: ...
    def combine(self, other: O) -> O: ...


TO = TypeVar('TO')


class ReduceableGatherable(Reduceable[TO], Gatherable[TO]):
    pass


class Dist:
    """Simulated distributed communication backend for multiple ranks."""
    def __init__(self, total: int) -> None:
        self.reduce: Optional[Any] = None
        self.gather: Optional[Any] = None
        self.ranks = total
        self.barrier = Barrier(total)
        self.queue: List[asyncio.Queue] = [
            asyncio.Queue(maxsize=1) for _ in range(total)
        ]
        self.mtime: float = 0

    async def allreduce(self, rank: int, inp: T, time: float) -> Tuple[T, float]:
        """Sum inp across all ranks. Returns (reduced_value, synced_time)."""
        if self.reduce is None:
            self.reduce = inp
        else:
            self.reduce = self.reduce + inp
        self.mtime = max(time, self.mtime)
        await self.barrier.wait(rank)
        q = self.reduce
        mtime = self.mtime
        await self.barrier.wait(rank)
        if rank == 0:
            self.reduce = None
            self.mtime = 0
        await self.barrier.wait(rank)
        return q, mtime

    async def allgather(self, rank: int, inp: O, time: float) -> Tuple[O, float]:
        """Gather shards from all ranks. Returns (complete_value, synced_time)."""
        if self.gather is None:
            self.gather = inp
        else:
            self.gather = self.gather.combine(inp)
        self.mtime = max(time, self.mtime)
        await self.barrier.wait(rank)
        q = self.gather
        mtime = self.mtime
        await self.barrier.wait(rank)
        if rank == 0:
            self.gather = None
            self.mtime = 0
        await self.barrier.wait(rank)
        return q, mtime

    async def scatterreduce(self, rank: int, inp, time: float):
        """AllReduce then shard: each rank gets its own shard of the sum."""
        x, time = await self.allreduce(rank, inp, time)
        y = x.shard(rank, self.ranks)
        return y, time

    async def receive(self, rank: int) -> Any:
        """Blocking receive from this rank's p2p queue."""
        return await self.queue[rank].get()

    async def pass_to(self, rank: int, v: Any) -> None:
        """Send value to target rank's p2p queue."""
        await self.queue[rank].put(v)


@dataclass
class Weight:
    """Model weight for a specific layer. Can be sharded across ranks."""
    layer: int
    layers: int
    step: int
    shards: FrozenSet[int] = field(default_factory=lambda: frozenset([0]))
    total: int = 1

    def combine(self, other: Weight) -> Weight:
        return Weight(self.layer, self.layers, self.step,
                      self.shards | other.shards, self.total)

    def memory(self) -> float:
        return (len(self.shards) / self.total) * HIDDEN * HIDDEN

    def shard(self, shard: int, total: int) -> Weight:
        assert self.is_complete()
        assert shard < total
        return Weight(self.layer, self.layers, self.step,
                      frozenset([shard]), total)

    def is_complete(self) -> bool:
        return len(self.shards) == self.total


@dataclass
class Activation:
    """Forward-pass activation at a given layer for a set of batches."""
    layer: int
    layers: int
    batches: FrozenSet[int]
    total_batches: int

    def memory(self) -> float:
        return len(self.batches) * HIDDEN * LENGTH


@dataclass
class WeightGrad:
    """Gradient of loss w.r.t. weights. Reduceable across batches, shardable."""
    layer: int
    layers: int
    batches: FrozenSet[int]
    total_batches: int
    shards: FrozenSet[int] = field(default_factory=lambda: frozenset([0]))
    total: int = 1

    def __add__(self, other: WeightGrad) -> WeightGrad:
        assert self.layer == other.layer, "Can only add same-layer grads"
        assert self.shards == other.shards
        return WeightGrad(self.layer, self.layers,
                          self.batches | other.batches, self.total_batches,
                          self.shards, self.total)

    def combine(self, other: WeightGrad) -> WeightGrad:
        return WeightGrad(self.layer, self.layers, self.batches,
                          self.total_batches,
                          self.shards | other.shards, self.total)

    def memory(self) -> float:
        return (len(self.shards) / self.total) * HIDDEN * HIDDEN

    def shard(self, shard: int, total: int) -> WeightGrad:
        assert self.is_complete(), f"{self.shards} out of {self.total}"
        assert shard < total
        return WeightGrad(self.layer, self.layers, self.batches,
                          self.total_batches, frozenset([shard]), total)

    def is_complete(self) -> bool:
        return len(self.shards) == self.total


@dataclass
class OptState:
    """Optimizer state (e.g. Adam moments) for a layer. Can be sharded."""
    layer: int
    layers: int
    step: int
    shards: FrozenSet[int] = field(default_factory=lambda: frozenset([0]))
    total: int = 1

    def combine(self, other: OptState) -> OptState:
        return OptState(self.layer, self.layers, self.step,
                        self.shards | other.shards, self.total)

    def memory(self) -> float:
        return HIDDEN * HIDDEN * (len(self.shards) / self.total)


@dataclass
class ActivationGrad:
    """Gradient of loss w.r.t. activations at a given layer."""
    layer: int
    layers: int
    batches: FrozenSet[int]
    total_batches: int

    def memory(self) -> float:
        return len(self.batches) * HIDDEN * LENGTH


class Model:
    """
    Simulated model on a single rank (GPU).

    Tracks symbolic forward/backward/update operations with assertions
    for correctness, and records simulated time and peak memory.

    Storage dictionaries:
      weights, opt_states, activations, grad_activations, grad_weights

    All stored objects contribute to memory(). Delete items from these
    dicts to free simulated memory. Only items in these dicts count.

    Communication methods (allreduce, allgather, scatterreduce, pass_to,
    receive) are async and must be called from all participating ranks.
    """
    def __init__(self, rank: int = 0, dist: Optional[Dist] = None,
                 layers: int = 2, batches: int = 1):
        if dist is None:
            dist = Dist(1)
        self.rank = rank
        self.time: float = 0
        self.peak_mem: float = 0
        self.dist = dist
        self.RANKS = dist.ranks
        self.LAYERS = layers
        self.BATCHES = batches
        self.final_weights: Dict[int, Weight] = {}
        self.weights: Dict[Any, Weight] = {}
        self.opt_states: Dict[Any, OptState] = {}
        self.activations: Dict[Any, Activation] = {}
        self.grad_activations: Dict[Any, ActivationGrad] = {}
        self.grad_weights: Dict[Any, WeightGrad] = {}

    def storage(self):
        """Return the 5 mutable storage dicts."""
        return (self.weights, self.opt_states, self.activations,
                self.grad_activations, self.grad_weights)

    def memory(self) -> float:
        """Total simulated memory across all stored objects."""
        mem = 0.0
        for d in self.storage():
            for v in d.values():
                mem += v.memory()
        return mem

    def _track(self):
        m = self.memory()
        if m > self.peak_mem:
            self.peak_mem = m

    def load_weights(self, layer: int, shard: int = 0,
                     total: int = 1) -> Tuple[Weight, OptState]:
        """Create initial weight and optimizer state for a layer."""
        return (Weight(layer, self.LAYERS, 0, frozenset([shard]), total),
                OptState(layer, self.LAYERS, 0, frozenset([shard]), total))

    def set_final_weight(self, layer: int, weight: Weight) -> None:
        """Register a weight as the final trained weight for verification."""
        self.final_weights[layer] = weight

    def get_activation(self, batches) -> Activation:
        """Get input activations for a set of batch indices."""
        return Activation(0, self.LAYERS, frozenset(batches), self.BATCHES)

    def forward(self, layer: int, inp: Activation,
                weight: Weight) -> Activation:
        """Forward pass: layer i activation -> layer i+1 activation."""
        assert weight.is_complete(), \
            f"Weight not complete: shards={weight.shards}, total={weight.total}"
        assert weight.layer == layer, \
            f"Weight layer {weight.layer} != expected {layer}"
        assert inp.layer == layer, \
            f"Input layer {inp.layer} != expected {layer}"
        self.time += len(inp.batches)
        self._track()
        return Activation(layer + 1, self.LAYERS, inp.batches, self.BATCHES)

    def backward(self, layer: int, inp: Activation, grad: ActivationGrad,
                 weight: Weight) -> Tuple[WeightGrad, ActivationGrad]:
        """Backward pass: returns (weight_grad, activation_grad_for_prev_layer)."""
        assert weight.is_complete()
        assert weight.layer == layer, \
            f"Weight layer {weight.layer} != {layer}"
        assert inp.layer == layer, \
            f"Input layer {inp.layer} != {layer}"
        assert set(inp.batches) == set(grad.batches), \
            f"Batch mismatch: {inp.batches} vs {grad.batches}"
        assert grad.layer == layer, \
            f"Grad layer {grad.layer} != {layer}"
        self.time += len(inp.batches)
        self._track()
        return (WeightGrad(layer, self.LAYERS, inp.batches, self.BATCHES),
                ActivationGrad(layer - 1, self.LAYERS, inp.batches,
                               self.BATCHES))

    def loss(self, inp: Activation) -> ActivationGrad:
        """Compute loss at the final layer, return gradient."""
        assert inp.layer == self.LAYERS, \
            f"Input layer {inp.layer} != final layer {self.LAYERS}"
        self._track()
        return ActivationGrad(self.LAYERS - 1, self.LAYERS, inp.batches,
                              self.BATCHES)

    def update(self, layer: int, weight_grad: WeightGrad, weight: Weight,
               opt_state: OptState) -> Tuple[Weight, OptState]:
        """Update weights using accumulated gradients. Requires all batches."""
        assert weight.layer == layer
        assert weight_grad.layer == layer
        assert set(weight_grad.batches) == set(range(self.BATCHES)), \
            f"Need all {self.BATCHES} batches, got {weight_grad.batches}"
        assert opt_state.layer == layer
        if weight_grad.total > 1:
            assert weight.shards.issubset(weight_grad.shards), \
                f"Weight shards {weight.shards} not in grad {weight_grad.shards}"
            assert opt_state.shards.issubset(weight_grad.shards), \
                f"Opt shards {opt_state.shards} not in grad {weight_grad.shards}"
        assert weight.step == opt_state.step, \
            f"Step mismatch: weight={weight.step}, opt={opt_state.step}"
        self.time += UPDATE_COST
        self._track()
        return (
            Weight(layer, self.LAYERS, weight.step + 1,
                   weight.shards, weight.total),
            OptState(layer, self.LAYERS, opt_state.step + 1,
                     opt_state.shards, opt_state.total)
        )

    def fake_grad(self, layer: int, batches) -> WeightGrad:
        """Create a WeightGrad with specified batches (for empty contributions)."""
        return WeightGrad(layer, self.LAYERS, frozenset(batches), self.BATCHES)

    async def allreduce(self, v, layer: int):
        """Sum a value across all ranks. Collective: all ranks must call."""
        v, self.time = await self.dist.allreduce(self.rank, v, self.time)
        self.time += COLLECTIVE_COST
        self._track()
        return v

    async def scatterreduce(self, v, layer: int):
        """AllReduce then shard: each rank gets its shard of the sum. Collective."""
        v, self.time = await self.dist.scatterreduce(self.rank, v, self.time)
        self.time += COLLECTIVE_COST
        self._track()
        return v

    async def allgather(self, v, layer: int):
        """Gather shards from all ranks into a complete object. Collective."""
        v, self.time = await self.dist.allgather(self.rank, v, self.time)
        self.time += COLLECTIVE_COST
        self._track()
        return v

    async def pass_to(self, rank: int, v: Any) -> None:
        """Send a value to a specific rank via point-to-point queue."""
        self.time += P2P_COST
        self._track()
        await self.dist.pass_to(rank, (v, self.time))

    async def receive(self) -> Any:
        """Receive a value from any sender via this rank's p2p queue."""
        v, time = await self.dist.receive(self.rank)
        self.time = max(time, self.time)
        self.time += P2P_COST
        self._track()
        return v

    @staticmethod
    def check(models: Sequence[Model]) -> bool:
        """
        Verify training correctness across all ranks.

        Checks that every layer has a complete, updated (step=1) final weight
        when combining shards across all models.
        """
        for l in range(models[0].LAYERS):
            weight = None
            for m in models:
                if l in m.final_weights:
                    assert m.final_weights[l].step == 1, \
                        f"Layer {l} rank {m.rank}: step={m.final_weights[l].step}, expected 1"
                    if weight is None:
                        weight = m.final_weights[l]
                    else:
                        weight = weight.combine(m.final_weights[l])
            assert weight is not None, f"No rank has final weight for layer {l}"
            assert weight.is_complete(), \
                f"Layer {l} incomplete: shards={weight.shards}, total={weight.total}"
        return True
