
"""
Distributed LLM Training Simulator

This module simulates distributed training of large language models across
multiple GPUs using asyncio. It provides abstractions for weights, activations,
gradients, and communication primitives (allreduce, allgather, scatter-reduce,
point-to-point).

The simulator tracks memory usage and step counts, allowing verification that
distributed training strategies meet efficiency targets.
"""

import asyncio
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Weight / gradient value abstraction
# ---------------------------------------------------------------------------

@dataclass
class Weight:
    """Represents model weights for a layer (or shard of a layer)."""
    layer: int
    version: int  # 0 = initial, incremented after update
    shards: frozenset  # which shards this covers
    total_shards: int
    size: int = 500_000  # memory per full weight

    @property
    def memory(self):
        return self.size * len(self.shards) // self.total_shards

    def combine(self, other: "Weight") -> "Weight":
        assert self.layer == other.layer and self.version == other.version
        assert self.total_shards == other.total_shards
        return Weight(self.layer, self.version,
                      self.shards | other.shards, self.total_shards, self.size)

    def shard_for(self, shard_id: int) -> "Weight":
        assert shard_id in self.shards
        return Weight(self.layer, self.version,
                      frozenset({shard_id}), self.total_shards, self.size)

    def __repr__(self):
        return f"W(L{self.layer},v{self.version},sh={sorted(self.shards)}/{self.total_shards})"


@dataclass
class OptState:
    """Optimizer state for a layer (or shard)."""
    layer: int
    shards: frozenset
    total_shards: int
    size: int = 500_000

    @property
    def memory(self):
        return self.size * len(self.shards) // self.total_shards


@dataclass
class Activation:
    """Forward-pass activation at a layer boundary."""
    layer: int  # layer index (0 = input, LAYERS = output)
    batches: frozenset
    size: int = 200_000

    @property
    def memory(self):
        return self.size * len(self.batches)

    def __repr__(self):
        return f"Act(L{self.layer},b={sorted(self.batches)})"


@dataclass
class GradActivation:
    """Gradient of loss w.r.t. activation at a layer boundary."""
    layer: int
    batches: frozenset
    size: int = 200_000

    @property
    def memory(self):
        return self.size * len(self.batches)


@dataclass
class WeightGrad:
    """Gradient of loss w.r.t. weights for a layer."""
    layer: int
    version: int
    batches: frozenset
    total_batches: int
    shards: frozenset = None
    total_shards: int = 1
    size: int = 500_000

    def __post_init__(self):
        if self.shards is None:
            self.shards = frozenset(range(self.total_shards))

    @property
    def memory(self):
        return self.size * len(self.shards) // self.total_shards

    def __add__(self, other: "WeightGrad") -> "WeightGrad":
        assert self.layer == other.layer
        assert self.total_batches == other.total_batches
        assert self.shards == other.shards
        return WeightGrad(self.layer, self.version,
                          self.batches | other.batches,
                          self.total_batches, self.shards,
                          self.total_shards, self.size)


# ---------------------------------------------------------------------------
# Distribution / communication layer
# ---------------------------------------------------------------------------

class Dist:
    """Manages inter-rank communication using asyncio barriers and queues."""

    def __init__(self, num_ranks: int):
        self.num_ranks = num_ranks
        # For allreduce / allgather / scatterreduce
        self._barriers: Dict[str, asyncio.Barrier] = {}
        self._stores: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        # For point-to-point
        self._p2p_queues: Dict[Tuple[int, int], asyncio.Queue] = {}
        for src in range(num_ranks):
            for dst in range(num_ranks):
                if src != dst:
                    self._p2p_queues[(src, dst)] = asyncio.Queue()

    async def _get_barrier(self, key: str) -> asyncio.Barrier:
        async with self._lock:
            if key not in self._barriers:
                self._barriers[key] = asyncio.Barrier(self.num_ranks)
                self._stores[key] = {}
            return self._barriers[key]

    async def allreduce(self, rank: int, data: WeightGrad, tag: int) -> WeightGrad:
        key = f"allreduce_{tag}"
        barrier = await self._get_barrier(key)
        self._stores[key][rank] = data
        await barrier.wait()
        result = None
        for r in range(self.num_ranks):
            if result is None:
                result = self._stores[key][r]
            else:
                result = result + self._stores[key][r]
        # Clean up after last waiter
        await barrier.wait()
        async with self._lock:
            if key in self._barriers:
                del self._barriers[key]
                del self._stores[key]
        return result

    async def allgather(self, rank: int, data: Weight, tag: int) -> Weight:
        key = f"allgather_{tag}"
        barrier = await self._get_barrier(key)
        self._stores[key][rank] = data
        await barrier.wait()
        result = None
        for r in range(self.num_ranks):
            if result is None:
                result = self._stores[key][r]
            else:
                result = result.combine(self._stores[key][r])
        await barrier.wait()
        async with self._lock:
            if key in self._barriers:
                del self._barriers[key]
                del self._stores[key]
        return result

    async def scatterreduce(self, rank: int, data: WeightGrad, tag: int) -> WeightGrad:
        """Scatter across shards, reduce across batches.
        Each rank contributes full-shard grad, gets back its own shard with all batches reduced."""
        key = f"scatterreduce_{tag}"
        barrier = await self._get_barrier(key)
        self._stores[key][rank] = data
        await barrier.wait()
        # Sum all grads, then extract shard for this rank
        total = None
        for r in range(self.num_ranks):
            item = self._stores[key][r]
            if total is None:
                total = item
            else:
                total = total + item
        # Return shard belonging to this rank
        result = WeightGrad(
            total.layer, total.version, total.batches, total.total_batches,
            frozenset({rank}), total.total_shards, total.size
        )
        await barrier.wait()
        async with self._lock:
            if key in self._barriers:
                del self._barriers[key]
                del self._stores[key]
        return result

    async def send(self, src: int, dst: int, data: Any):
        await self._p2p_queues[(src, dst)].put(data)

    async def recv(self, src: int, dst: int) -> Any:
        return await self._p2p_queues[(src, dst)].get()


# ---------------------------------------------------------------------------
# Model (per-rank)
# ---------------------------------------------------------------------------

class Model:
    """Per-rank model that tracks operations, memory, and correctness."""

    def __init__(self, layers: int, batches: int, rank: int = 0,
                 dist: Optional[Dist] = None):
        self.LAYERS = layers
        self.BATCHES = batches
        self.RANKS = dist.num_ranks if dist else 1
        self.rank = rank
        self.dist = dist

        # Storage dictionaries
        self.weights: Dict = {}
        self.opt_states: Dict = {}
        self.activations: Dict = {}
        self.grad_activations: Dict = {}
        self.grad_weights: Dict = {}

        # Tracking
        self._steps = 0
        self._max_memory = 0
        self._current_memory = 0
        self._memory_log: List[int] = []
        self.final_weights: Dict[int, Weight] = {}

        # Communication tag counters
        self._allreduce_tag = 0
        self._allgather_tag = 0
        self._scatterreduce_tag = 0

        # Deterministic "random" weights based on layer
        self._rng_state = 42 + rank

    def storage(self):
        return (self.weights, self.opt_states, self.activations,
                self.grad_activations, self.grad_weights)

    def _track_memory(self):
        mem = 0
        for v in self.weights.values():
            mem += v.memory
        for v in self.opt_states.values():
            mem += v.memory
        for v in self.activations.values():
            mem += v.memory
        for v in self.grad_activations.values():
            mem += v.memory
        for v in self.grad_weights.values():
            mem += v.memory
        self._current_memory = mem
        self._max_memory = max(self._max_memory, mem)
        self._memory_log.append(mem)

    def _step(self):
        self._steps += 1
        self._track_memory()

    def memory(self) -> int:
        self._track_memory()
        return self._current_memory

    def max_memory(self) -> int:
        return self._max_memory

    def steps(self) -> int:
        return self._steps

    # --- Core operations ---

    def load_weights(self, layer: int, shard: Optional[int] = None,
                     total: Optional[int] = None) -> Tuple[Weight, OptState]:
        if shard is not None and total is not None:
            w = Weight(layer, 0, frozenset({shard}), total)
            o = OptState(layer, frozenset({shard}), total)
        else:
            w = Weight(layer, 0, frozenset(range(1)), 1)
            o = OptState(layer, frozenset(range(1)), 1)
        self._step()
        return w, o

    def get_activation(self, batches) -> Activation:
        self._step()
        return Activation(0, frozenset(batches))

    def forward(self, layer: int, inp: Activation, weight: Weight) -> Activation:
        assert inp.layer == layer, f"Expected activation at layer {layer}, got {inp.layer}"
        assert layer in [s for s in range(self.LAYERS)], f"Invalid layer {layer}"
        # Weight must cover all shards
        assert len(weight.shards) == weight.total_shards, \
            f"Forward needs full weight, got shards {weight.shards}/{weight.total_shards}"
        self._step()
        return Activation(layer + 1, inp.batches)

    def loss(self, act: Activation) -> GradActivation:
        assert act.layer == self.LAYERS, \
            f"Loss requires activation at final layer {self.LAYERS}, got {act.layer}"
        self._step()
        return GradActivation(self.LAYERS, act.batches)

    def backward(self, layer: int, inp_act: Activation, grad_act: GradActivation,
                 weight: Weight) -> Tuple[WeightGrad, GradActivation]:
        assert inp_act.layer == layer
        assert grad_act.layer == layer + 1
        assert len(weight.shards) == weight.total_shards, \
            "Backward needs full weight"
        assert inp_act.batches == grad_act.batches, \
            f"Batch mismatch: act {inp_act.batches} vs grad {grad_act.batches}"
        self._step()
        wg = WeightGrad(layer, weight.version, inp_act.batches, self.BATCHES)
        ga = GradActivation(layer, inp_act.batches)
        return wg, ga

    def update(self, layer: int, weight_grad: WeightGrad, weight: Weight,
               opt_state: OptState) -> Tuple[Weight, OptState]:
        assert weight_grad.batches == frozenset(range(self.BATCHES)), \
            f"Update needs all batches {set(range(self.BATCHES))}, got {weight_grad.batches}"
        assert weight.shards == weight_grad.shards or \
               len(weight_grad.shards) == weight_grad.total_shards, \
            "Shard mismatch in update"
        self._step()
        new_w = Weight(layer, weight.version + 1, weight.shards, weight.total_shards)
        new_o = OptState(layer, opt_state.shards, opt_state.total_shards)
        return new_w, new_o

    def set_final_weight(self, layer: int, weight: Weight):
        self.final_weights[layer] = weight

    def fake_grad(self, layer: int, batches: list) -> WeightGrad:
        return WeightGrad(layer, 0, frozenset(batches), self.BATCHES)

    # --- Communication wrappers ---

    async def allreduce(self, grad: WeightGrad, tag: Optional[int] = None) -> WeightGrad:
        if tag is None:
            tag = self._allreduce_tag
            self._allreduce_tag += 1
        self._step()
        return await self.dist.allreduce(self.rank, grad, tag)

    async def allgather(self, weight: Weight, tag: Optional[int] = None) -> Weight:
        if tag is None:
            tag = self._allgather_tag
            self._allgather_tag += 1
        self._step()
        return await self.dist.allgather(self.rank, weight, tag)

    async def scatterreduce(self, grad: WeightGrad, tag: Optional[int] = None) -> WeightGrad:
        if tag is None:
            tag = self._scatterreduce_tag
            self._scatterreduce_tag += 1
        self._step()
        return await self.dist.scatterreduce(self.rank, grad, tag)

    async def pass_to(self, dst: int, data: Any):
        self._step()
        await self.dist.send(self.rank, dst, data)

    async def receive(self, src: int) -> Any:
        self._step()
        return await self.dist.recv(src, self.rank)

    # --- Verification ---

    @staticmethod
    def check(models: list) -> dict:
        """Verify that all models computed the correct final weights.
        Returns dict with 'steps', 'max_memory', 'passed' keys."""
        all_passed = True
        total_steps = 0
        max_mem = 0

        for m in models:
            # Every layer must have a final weight
            for l in range(m.LAYERS):
                if l not in m.final_weights:
                    print(f"FAIL: Rank {m.rank} missing final weight for layer {l}")
                    all_passed = False
                    continue
                fw = m.final_weights[l]
                if fw.version < 1:
                    print(f"FAIL: Rank {m.rank} layer {l} weight not updated (version {fw.version})")
                    all_passed = False

            total_steps = max(total_steps, m.steps())
            max_mem = max(max_mem, m.max_memory())

        # All ranks should have identical final weights (same version)
        if len(models) > 1:
            for l in range(models[0].LAYERS):
                versions = set()
                for m in models:
                    if l in m.final_weights:
                        versions.add(m.final_weights[l].version)
                if len(versions) > 1:
                    print(f"FAIL: Layer {l} has inconsistent versions across ranks: {versions}")
                    all_passed = False

        return {
            "passed": all_passed,
            "steps": total_steps,
            "max_memory": max_mem,
        }
