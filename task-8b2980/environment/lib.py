"""
Distributed training simulation framework.
Simulates multi-GPU neural network training using asyncio,
tracking time steps and memory usage across ranks.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, FrozenSet, TypeVar


class Barrier:
    """Synchronization barrier for n ranks."""
    def __init__(self, target: int):
        self.counter = 0
        self.target = target
        self.lock = asyncio.Lock()
        self.round = 0
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
            await self.reset()

    async def reset(self) -> None:
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


HIDDEN = 512
LENGTH = 256


class Dist:
    """Distribution coordinator for simulated GPU ranks."""
    def __init__(self, total: int) -> None:
        self.reduce: Optional[Any] = None
        self.gather: Optional[Any] = None
        self.ranks = total
        self.barrier = Barrier(total)
        self.queue: Sequence[asyncio.Queue[Any]] = [asyncio.Queue(maxsize=1) for _ in range(total)]
        self.mtime = 0

    async def allreduce(self, rank: int, inp: T, time: int) -> Tuple[T, int]:
        if self.reduce is None:
            self.reduce = inp
        else:
            self.reduce = self.reduce + inp
        self.mtime = max(time, self.mtime)
        await self.barrier.wait(rank)
        q: T = self.reduce
        mtime = self.mtime
        await self.barrier.wait(rank)
        if rank == 0:
            self.reduce = None
            self.mtime = 0
        await self.barrier.wait(rank)
        return q, mtime

    async def allgather(self, rank: int, inp: O, time: int) -> Tuple[O, int]:
        if self.gather is None:
            self.gather = inp
        else:
            assert type(self.gather) == type(inp)
            self.gather = self.gather.combine(inp)
        self.mtime = max(time, self.mtime)
        await self.barrier.wait(rank)
        q: O = self.gather
        mtime = self.mtime
        await self.barrier.wait(rank)
        if rank == 0:
            self.gather = None
            self.mtime = 0
        await self.barrier.wait(rank)
        return q, mtime

    async def scatterreduce(self, rank: int, inp: TO, time: int) -> Tuple[TO, int]:
        x, time = await self.allreduce(rank, inp, time)
        y = x.shard(rank, self.ranks)
        return y, time

    async def receive(self, rank: int) -> Any:
        return await self.queue[rank].get()

    async def pass_to(self, rank: int, v: Any) -> None:
        await self.queue[rank].put(v)


@dataclass
class Weight(Gatherable["Weight"]):
    """
    Weights for a specific layer. Can be sharded across ranks.
    Required for forward and backward passes.
    """
    layer: int
    layers: int
    step: int
    shards: FrozenSet[int] = frozenset([0])
    total: int = 1

    def combine(self, other: Weight) -> Weight:
        return Weight(self.layer, self.layers, self.step, self.shards | other.shards, self.total)

    def memory(self) -> float:
        return (len(self.shards) / self.total) * HIDDEN * HIDDEN

    def shard(self, shard: int, total: int) -> Weight:
        assert self.is_complete()
        assert shard < total
        return Weight(self.layer, self.layers, self.step, frozenset([shard]), total)

    def is_complete(self) -> bool:
        return len(self.shards) == self.total


@dataclass
class Activation:
    """
    Activations for a specific layer and set of batches.
    Produced by forward pass, consumed by backward pass.
    """
    layer: int
    layers: int
    batches: FrozenSet[int]
    total_batches: int

    def memory(self) -> int:
        return len(self.batches) * HIDDEN * LENGTH


@dataclass
class WeightGrad(Reduceable["WeightGrad"], Gatherable["WeightGrad"]):
    """
    Gradient of loss w.r.t. weights for a specific layer.
    May be sharded and/or split across batches.
    Supports addition (combines batches) and sharding.
    """
    layer: int
    layers: int
    batches: FrozenSet[int]
    total_batches: int
    shards: FrozenSet[int] = frozenset([0])
    total: int = 1

    def __add__(self, other: WeightGrad) -> WeightGrad:
        assert self.layer == other.layer, "Only add same layer weight grads"
        assert self.shards == other.shards
        return WeightGrad(self.layer, self.layers, self.batches | other.batches, self.total_batches,
                          self.shards, self.total)

    def combine(self, other: WeightGrad) -> WeightGrad:
        return WeightGrad(self.layer, self.layers, self.batches, self.total_batches,
                          self.shards | other.shards, self.total)

    def memory(self) -> float:
        return (len(self.shards) / self.total) * HIDDEN * HIDDEN

    def shard(self, shard: int, total: int) -> WeightGrad:
        assert self.is_complete(), f"{self.shards} out of {self.total}"
        assert shard < total
        return WeightGrad(self.layer, self.layers, self.batches, self.total_batches, frozenset([shard]), total)

    def is_complete(self) -> bool:
        return len(self.shards) == self.total


@dataclass
class OptState(Gatherable["OptState"]):
    """
    Optimizer state (e.g. ADAM moments) for a specific layer.
    Can be sharded. Required for weight updates.
    """
    layer: int
    layers: int
    step: int
    shards: FrozenSet[int] = frozenset([0])
    total: int = 1

    def combine(self, other: OptState) -> OptState:
        return OptState(self.layer, self.layers, self.step, self.shards | other.shards, self.total)

    def memory(self) -> float:
        return HIDDEN * HIDDEN * (len(self.shards) / self.total)


@dataclass
class ActivationGrad:
    """
    Gradient of loss w.r.t. activations for a specific layer.
    Produced by backward pass, consumed by the previous layer's backward.
    """
    layer: int
    layers: int
    batches: FrozenSet[int]
    total_batches: int

    def memory(self) -> int:
        return len(self.batches) * HIDDEN * LENGTH


@dataclass
class Event:
    """Record of a simulation event for timing and memory tracking."""
    typ: str
    layer: Optional[int]
    rank: int
    time: int
    length: int
    memory: int
    batches: FrozenSet[int] = frozenset()


class Model:
    """
    Simulated GPU rank for distributed training.

    Provides computation operations (forward, backward, loss, update) and
    communication primitives (allreduce, allgather, scatterreduce, pass_to/receive).

    All state must be stored in the provided dictionaries (weights, opt_states,
    activations, grad_activations, grad_weights). Memory is computed from these
    dictionaries. Use del to free memory.

    Usage:
        weights, opt_states, activations, grad_activations, grad_weights = model.storage()

        # Load weights (optionally sharded)
        weights[l], opt_states[l] = model.load_weights(layer, shard=0, total=1)

        # Get input activations for specific batches
        activations[0] = model.get_activation([batch_id])

        # Forward: activation[l] + weight[l] -> activation[l+1]
        activations[l+1] = model.forward(l, activations[l], weights[l])

        # Loss: activation[LAYERS] -> grad_activation[LAYERS]
        grad_activations[LAYERS] = model.loss(activations[LAYERS])

        # Backward: activation[l] + grad_activation[l+1] + weight[l] -> (weight_grad[l], grad_activation[l])
        grad_weights[l], grad_activations[l] = model.backward(l, activations[l], grad_activations[l+1], weights[l])

        # Update: weight[l] + grad_weight[l] + opt_state[l] -> (new_weight[l], new_opt_state[l])
        weights[l], opt_states[l] = model.update(l, grad_weights[l], weights[l], opt_states[l])

        # Communication (async):
        result = await model.allreduce(value, layer)      # Sum across all ranks
        result = await model.allgather(value, layer)       # Gather shards from all ranks
        result = await model.scatterreduce(value, layer)   # Allreduce then shard back
        await model.pass_to(target_rank, value)            # Point-to-point send
        value = await model.receive()                      # Point-to-point receive

        # Finalize
        model.set_final_weight(layer, weight)
    """

    def __init__(self, rank: int = 1, dist: Dist = Dist(1), layers: int = 2, batches: int = 1):
        self.rank = rank
        self.log: List[Event] = []
        self.dist = dist
        self.time = 0
        self.RANKS = dist.ranks
        self.LAYERS = layers
        self.BATCHES = batches
        self.final_weights: Dict[int, Weight] = {}

        self.weights: Dict[Any, Weight] = {}
        self.opt_states: Dict[Any, OptState] = {}
        self.activations: Dict[Any, Activation] = {}
        self.grad_activations: Dict[Any, ActivationGrad] = {}
        self.grad_weights: Dict[Any, WeightGrad] = {}

    def storage(self) -> Tuple[Dict[Any, Weight], Dict[Any, OptState], Dict[Any, Activation], Dict[Any, ActivationGrad], Dict[Any, WeightGrad]]:
        """Return references to the five state dictionaries."""
        return self.weights, self.opt_states, self.activations, self.grad_activations, self.grad_weights

    def memory(self) -> int:
        """Current total memory across all stored state."""
        mem = 0
        for d in list(self.storage()):
            assert isinstance(d, dict)
            for v in d.values():
                mem += v.memory()
        return mem

    def peak_memory(self) -> int:
        """Peak memory observed across all logged events."""
        if not self.log:
            return self.memory()
        return max(e.memory for e in self.log)

    def event(self, typ: str, layer: Optional[int] = None, batches: FrozenSet[int] = frozenset()) -> None:
        length = 0
        if typ in ["loss", "allgather"]:
            length = 0
        if typ in ["forward", "backward"]:
            length = len(batches)
        if typ in ["update"]:
            length = 0.5
        if typ in ["allreduce", "scatterreduce", "allgather"]:
            length = 0.3
        if typ in ["pass"]:
            length = 0.2
        self.log.append(Event(typ, layer, self.rank, self.time, length, self.memory(), batches))
        self.time += length

    def load_weights(self, layer: int, shard: int = 0, total: int = 1) -> Tuple[Weight, OptState]:
        """Load (optionally sharded) weights and optimizer state for a layer."""
        return Weight(layer, self.LAYERS, 0, frozenset([shard]), total), \
               OptState(layer, self.LAYERS, 0, frozenset([shard]), total)

    def set_final_weight(self, layer: int, weight: Weight) -> None:
        """Register the final updated weight for verification."""
        self.final_weights[layer] = weight

    def get_activation(self, batches: Sequence[int]) -> Activation:
        """Get input activations for specified batch indices."""
        return Activation(0, self.LAYERS, frozenset(batches), self.BATCHES)

    def forward(self, layer: int, inp: Activation, weight: Weight) -> Activation:
        """Forward pass: activation[layer] + weight[layer] -> activation[layer+1]."""
        self.event("forward", layer, inp.batches)
        assert weight.is_complete(), f"Weight must be complete for forward, got shards {weight.shards}/{weight.total}"
        assert weight.layer == layer, f"Weight should be layer {layer}"
        assert inp.layer == layer, f"Input should be layer {layer}"
        return Activation(layer + 1, self.LAYERS, inp.batches, self.BATCHES)

    def backward(self, layer: int, inp: Activation, grad: ActivationGrad, weight: Weight) -> Tuple[WeightGrad, ActivationGrad]:
        """Backward pass: returns (weight_grad, activation_grad for layer-1)."""
        self.event("backward", layer, inp.batches)
        assert weight.is_complete(), f"Weight must be complete for backward"
        assert weight.layer == layer, f"Weight should be layer {layer}"
        assert inp.layer == layer, f"Input should be layer {layer}"
        assert set(inp.batches) == set(grad.batches), f"Batch mismatch {set(inp.batches)}"
        assert grad.layer == layer, f"Activation Grad should be layer {layer}"
        return (WeightGrad(layer, self.LAYERS, inp.batches, self.BATCHES),
                ActivationGrad(layer - 1, self.LAYERS, inp.batches, self.BATCHES))

    def loss(self, inp: Activation) -> ActivationGrad:
        """Compute loss gradient from final-layer activation."""
        self.event("loss", self.LAYERS)
        assert inp.layer == self.LAYERS, f"Input should be final layer {self.LAYERS}"
        return ActivationGrad(self.LAYERS - 1, self.LAYERS, inp.batches, self.BATCHES)

    def update(self, layer: int, weight_grad: WeightGrad, weight: Weight, opt_state: OptState, shard: int = 0) -> Tuple[Weight, OptState]:
        """Update weights using accumulated gradients. Gradients must cover all batches."""
        assert weight.layer == layer, f"Weight should be layer {layer}"
        assert weight_grad.layer == layer, f"Grad weight should be layer {layer}"
        assert set(weight_grad.batches) == set(range(self.BATCHES)), \
            f"Gradient must cover all batches, got {set(weight_grad.batches)} need {set(range(self.BATCHES))}"
        assert opt_state.layer == layer
        if weight_grad.total > 1:
            assert weight.shards.issubset(weight_grad.shards), f"Weight shards {weight.shards} not in grad shards {weight_grad.shards}"
            assert opt_state.shards.issubset(weight_grad.shards), f"Opt shards {opt_state.shards} not in grad shards {weight_grad.shards}"
        assert weight.step == opt_state.step
        new_opt = OptState(layer, self.LAYERS, opt_state.step + 1, opt_state.shards, opt_state.total)
        new_weight = Weight(layer, self.LAYERS, weight.step + 1, weight.shards, weight.total)
        self.event("update", None)
        return new_weight, new_opt

    def fake_grad(self, layer: int, batches=List[int]):
        """Create a WeightGrad with specified batches (useful for empty gradients)."""
        return WeightGrad(layer, self.LAYERS, frozenset(batches), self.BATCHES)

    async def allreduce(self, v: T, layer: int) -> T:
        """Sum a value across all ranks. All ranks must call simultaneously."""
        v, self.time = await self.dist.allreduce(self.rank, v, self.time)
        self.event("allreduce", layer)
        return v

    async def scatterreduce(self, v: TO, layer: int) -> TO:
        """Allreduce then shard the result back to each rank."""
        v, self.time = await self.dist.scatterreduce(self.rank, v, self.time)
        self.event("scatterreduce", layer)
        return v

    async def allgather(self, v: O, layer: int) -> O:
        """Gather and combine shards from all ranks."""
        v, self.time = await self.dist.allgather(self.rank, v, self.time)
        self.event("allgather", layer)
        return v

    async def pass_to(self, rank: int, v: Any) -> None:
        """Send a value to a specific rank (point-to-point)."""
        self.event("pass", None)
        await self.dist.pass_to(rank, (v, self.time))

    async def receive(self) -> Any:
        """Receive a value from any rank (point-to-point)."""
        v, time = await self.dist.receive(self.rank)
        self.time = max(time, self.time)
        self.event("pass", None)
        return v

    @staticmethod
    def check(models: Sequence["Model"]) -> None:
        """
        Verify correctness: all layer weights must be updated exactly once
        and be complete (all shards present) across ranks.
        Raises AssertionError on failure.
        """
        for l in range(models[0].LAYERS):
            weight = None
            for m in models:
                if l in m.final_weights:
                    assert m.final_weights[l].step == 1, \
                        f"Layer {l} weight step should be 1, got {m.final_weights[l].step}"
                    if weight is None:
                        weight = m.final_weights[l]
                    else:
                        weight = weight.combine(m.final_weights[l])
            assert weight is not None, f"Missing final weight for layer {l}"
            assert weight.is_complete(), f"Weight for layer {l} not complete: {weight}"
