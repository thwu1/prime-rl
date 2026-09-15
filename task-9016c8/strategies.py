
"""
Distributed Training Strategies

Implement the following 5 distributed training strategies using the simulator
framework. Each strategy is an async function that takes a Model and returns it
with final weights set. All strategies must pass Model.check() AND meet the
specified step and memory targets.

See /app/simulator.py for the Model API.

All persistent tensors (activations saved for backward, gathered full weights,
etc.) must be stored in the model's storage dicts using any hashable key.
Delete entries (del dict[key]) when no longer needed to reduce peak memory.
"""

import asyncio
from simulator import Model, Dist, WeightGrad


# ---------------------------------------------------------------------------
# Strategy 1: Standard Training (single device, all batches at once)
#
# Run forward on all batches, compute loss, backward, update.
# Delete intermediate storage when no longer needed to minimize memory.
#
# Config: layers=2, batches=4, ranks=1
# Target Steps:  <= 12
# Target Max Memory: <= 4,600,000
# ---------------------------------------------------------------------------

def basic(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l)
    activations[0] = model.get_activation(range(model.BATCHES))

    # TODO: Implement standard training loop
    # 1. Forward pass through all layers
    # 2. Compute loss at final layer
    # 3. Backward pass through all layers (reverse order)
    # 4. Update weights for all layers
    # Delete activations/gradients from dicts when no longer needed
    raise NotImplementedError("Implement basic training strategy")

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


# ---------------------------------------------------------------------------
# Strategy 2: Gradient Accumulation (single device, one batch at a time)
#
# Process each batch individually to reduce peak memory. Accumulate gradients
# across batches, then update.
#
# Config: layers=2, batches=4, ranks=1
# Target Steps:  <= 32
# Target Max Memory: <= 3,800,000
# ---------------------------------------------------------------------------

def grad_accum(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l)

    # TODO: Implement gradient accumulation
    # For each batch individually:
    #   get_activation, forward, loss, backward, accumulate grad_weights
    # Then update all layers with accumulated gradients
    raise NotImplementedError("Implement gradient accumulation strategy")

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


# ---------------------------------------------------------------------------
# Strategy 3: Distributed Data Parallel (DDP)
#
# Each rank processes one batch. Use allreduce to sum gradients across ranks.
#
# Config: layers=2, batches=4, ranks=4
# Target Steps:  <= 14
# Target Max Memory: <= 3,400,000
# ---------------------------------------------------------------------------

async def ddp(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    activations[0] = model.get_activation([model.rank])

    # TODO: Implement DDP
    # 1. Load full weights on each rank
    # 2. Forward, loss, backward with this rank's batch
    # 3. AllReduce gradients for each layer (tag=layer_index)
    # 4. Update weights
    raise NotImplementedError("Implement DDP strategy")

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


# ---------------------------------------------------------------------------
# Strategy 4: Fully-Sharded Data Parallel (FSDP)
#
# Each rank stores only a shard of each layer's weights/optimizer. Use
# allgather to reconstruct full weights before forward/backward, and
# scatter-reduce to distribute gradient shards after backward.
#
# Config: layers=6, batches=4, ranks=4
# Target Steps:  <= 50
# Target Max Memory: <= 5,200,000
# ---------------------------------------------------------------------------

async def fsdp(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    activations[0] = model.get_activation([model.rank])

    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l, model.rank, model.RANKS)

    # TODO: Implement FSDP
    # Forward: for each layer, allgather full weight (store as weights[("full", l)]),
    #   forward, delete full weight
    # Loss at final layer
    # Backward: for each layer (reverse), allgather again, backward,
    #   scatter-reduce gradients, delete full weight and used activations
    # Update: each rank updates its shard
    raise NotImplementedError("Implement FSDP strategy")

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


# ---------------------------------------------------------------------------
# Strategy 5: Pipeline Parallelism + FSDP (combined)
#
# 16 ranks organized into 4 pipeline stages of 4 FSDP ranks each.
# pipeline_stage = rank // 4, fsdp_rank = rank % 4
# Each stage handles one layer. Weights sharded within each stage's FSDP group.
#
# Since global allgather/scatterreduce require all 16 ranks, intra-group
# FSDP operations must use point-to-point (pass_to/receive) within each
# pipeline stage group.
#
# Config: layers=4, batches=4, ranks=16
# Target Steps:  <= 90
# Target Max Memory: <= 2,400,000
# ---------------------------------------------------------------------------

async def pipeline_fsdp(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    fsdp_group_size = 4
    pipeline_stage = model.rank // fsdp_group_size  # 0..3
    fsdp_rank = model.rank % fsdp_group_size         # 0..3
    my_layer = pipeline_stage
    num_stages = model.LAYERS  # 4

    # Load sharded weight - sharded across FSDP group (4 ranks), not all 16
    weights[my_layer], opt_states[my_layer] = model.load_weights(
        my_layer, fsdp_rank, fsdp_group_size
    )

    # TODO: Implement Pipeline + FSDP
    # Implement helper functions for intra-group allgather and scatter-reduce
    # using point-to-point communication within the pipeline stage group.
    #
    # Forward (for each micro-batch b=0..3):
    #   Stage 0: get_activation([b])
    #   Other stages: receive from prev stage's corresponding rank
    #   Store activation in activations[(my_layer, b)] for backward
    #   Allgather weight within group -> weights[("full", my_layer)]
    #   Forward pass, delete full weight
    #   Last stage: compute loss -> grad_activations[(my_layer+1, b)]
    #   Other stages: pass_to next stage's corresponding rank
    #
    # Backward (for each micro-batch b=3..0):
    #   Last stage: use stored grad_activation
    #   Other stages: receive from next stage
    #   Allgather weight, backward, accumulate grad_weights[my_layer]
    #   Non-first stages: pass_to prev stage
    #
    # Scatter-reduce accumulated grads within group
    # Update local shard
    raise NotImplementedError("Implement Pipeline+FSDP strategy")

    from simulator import Weight
    for l in range(model.LAYERS):
        if l == my_layer:
            model.set_final_weight(l, weights[my_layer])
        else:
            model.set_final_weight(l, Weight(l, 1, frozenset({0}), 1))
    return model
