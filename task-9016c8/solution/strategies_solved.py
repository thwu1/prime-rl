
"""
Solved implementations of all 5 distributed training strategies.
"""

import asyncio
from simulator import Model, Dist, WeightGrad, Weight


# ---------------------------------------------------------------------------
# Strategy 1: Standard Training
# ---------------------------------------------------------------------------

def basic(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l)
    activations[0] = model.get_activation(range(model.BATCHES))

    # Forward pass
    for l in range(model.LAYERS):
        activations[l + 1] = model.forward(l, activations[l], weights[l])

    # Loss
    grad_activations[model.LAYERS] = model.loss(activations[model.LAYERS])
    del activations[model.LAYERS]

    # Backward pass
    for l in range(model.LAYERS - 1, -1, -1):
        grad_weights[l], grad_activations[l] = model.backward(
            l, activations[l], grad_activations[l + 1], weights[l]
        )
        del activations[l]
        del grad_activations[l + 1]

    # Update
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l], opt_states[l]
        )
        del grad_weights[l]

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


# ---------------------------------------------------------------------------
# Strategy 2: Gradient Accumulation
# ---------------------------------------------------------------------------

def grad_accum(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l)

    for b in range(model.BATCHES):
        activations[0] = model.get_activation([b])

        # Forward
        for l in range(model.LAYERS):
            activations[l + 1] = model.forward(l, activations[l], weights[l])

        # Loss
        grad_activations[model.LAYERS] = model.loss(activations[model.LAYERS])
        del activations[model.LAYERS]

        # Backward
        for l in range(model.LAYERS - 1, -1, -1):
            wg, grad_activations[l] = model.backward(
                l, activations[l], grad_activations[l + 1], weights[l]
            )
            del activations[l]
            del grad_activations[l + 1]

            # Accumulate
            if l in grad_weights:
                grad_weights[l] = grad_weights[l] + wg
            else:
                grad_weights[l] = wg

        if 0 in grad_activations:
            del grad_activations[0]

    # Update
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l], opt_states[l]
        )
        del grad_weights[l]

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


# ---------------------------------------------------------------------------
# Strategy 3: DDP
# ---------------------------------------------------------------------------

async def ddp(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    activations[0] = model.get_activation([model.rank])

    # Load full weights
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l)

    # Forward
    for l in range(model.LAYERS):
        activations[l + 1] = model.forward(l, activations[l], weights[l])

    # Loss
    grad_activations[model.LAYERS] = model.loss(activations[model.LAYERS])
    del activations[model.LAYERS]

    # Backward
    for l in range(model.LAYERS - 1, -1, -1):
        grad_weights[l], grad_activations[l] = model.backward(
            l, activations[l], grad_activations[l + 1], weights[l]
        )
        del activations[l]
        del grad_activations[l + 1]

    # AllReduce gradients
    for l in range(model.LAYERS):
        grad_weights[l] = await model.allreduce(grad_weights[l], tag=l)

    # Update
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l], opt_states[l]
        )
        del grad_weights[l]

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


# ---------------------------------------------------------------------------
# Strategy 4: FSDP
# ---------------------------------------------------------------------------

async def fsdp(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    activations[0] = model.get_activation([model.rank])

    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l, model.rank, model.RANKS)

    # Forward: allgather weights, forward, delete full weight
    for l in range(model.LAYERS):
        # Gather full weight, store temporarily with composite key
        weights[("full", l)] = await model.allgather(weights[l], tag=l)
        activations[l + 1] = model.forward(l, activations[l], weights[("full", l)])
        del weights[("full", l)]

    # Loss
    grad_activations[model.LAYERS] = model.loss(activations[model.LAYERS])
    del activations[model.LAYERS]

    # Backward: allgather weights again, backward, scatter-reduce grads
    for l in range(model.LAYERS - 1, -1, -1):
        weights[("full", l)] = await model.allgather(weights[l], tag=model.LAYERS + l)
        grad_weights[l], grad_activations[l] = model.backward(
            l, activations[l], grad_activations[l + 1], weights[("full", l)]
        )
        del weights[("full", l)]
        del activations[l]
        del grad_activations[l + 1]

        # Scatter-reduce
        grad_weights[l] = await model.scatterreduce(grad_weights[l], tag=l)

    # Update local shard
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l], opt_states[l]
        )
        del grad_weights[l]

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


# ---------------------------------------------------------------------------
# Strategy 5: Pipeline + FSDP
# ---------------------------------------------------------------------------

async def pipeline_fsdp(model: Model) -> Model:
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    fsdp_group_size = 4
    pipeline_stage = model.rank // fsdp_group_size  # 0..3
    fsdp_rank = model.rank % fsdp_group_size         # 0..3
    my_layer = pipeline_stage
    num_stages = model.LAYERS  # 4

    # Load sharded weight for my layer - sharded across FSDP group (4 ranks)
    weights[my_layer], opt_states[my_layer] = model.load_weights(
        my_layer, fsdp_rank, fsdp_group_size
    )

    async def fsdp_allgather_in_group(my_shard_weight):
        """AllGather weight within the pipeline stage's FSDP group using p2p."""
        group_start = pipeline_stage * fsdp_group_size
        group_ranks = list(range(group_start, group_start + fsdp_group_size))

        # Send my shard to all others in group
        sends = []
        for r in group_ranks:
            if r != model.rank:
                model._step()
                sends.append(model.dist.send(model.rank, r, my_shard_weight))
        await asyncio.gather(*sends)

        # Receive shards from all others
        result = my_shard_weight
        recvs = []
        for r in group_ranks:
            if r != model.rank:
                model._step()
                recvs.append(model.dist.recv(r, model.rank))
        shards = await asyncio.gather(*recvs)
        for shard in shards:
            result = result.combine(shard)

        return result

    async def fsdp_scatterreduce_in_group(full_grad):
        """ScatterReduce grad within the pipeline stage's FSDP group using p2p."""
        group_start = pipeline_stage * fsdp_group_size
        group_ranks = list(range(group_start, group_start + fsdp_group_size))

        # Send full grad to all others
        sends = []
        for r in group_ranks:
            if r != model.rank:
                model._step()
                sends.append(model.dist.send(model.rank, r, full_grad))
        await asyncio.gather(*sends)

        # Receive from all others and sum
        total = full_grad
        recvs = []
        for r in group_ranks:
            if r != model.rank:
                model._step()
                recvs.append(model.dist.recv(r, model.rank))
        others = await asyncio.gather(*recvs)
        for other_grad in others:
            total = total + other_grad

        # Return only my shard
        return WeightGrad(
            total.layer, total.version, total.batches, total.total_batches,
            frozenset({fsdp_rank}), total.total_shards, total.size
        )

    # Determine prev/next stage rank (use corresponding fsdp_rank in other stage)
    prev_stage_rank = ((pipeline_stage - 1) * fsdp_group_size + fsdp_rank
                       if pipeline_stage > 0 else None)
    next_stage_rank = ((pipeline_stage + 1) * fsdp_group_size + fsdp_rank
                       if pipeline_stage < num_stages - 1 else None)

    for b in range(model.BATCHES):
        # --- Forward for micro-batch b ---
        if pipeline_stage == 0:
            activations[(my_layer, b)] = model.get_activation([b])
        else:
            activations[(my_layer, b)] = await model.receive(prev_stage_rank)

        # AllGather weight within FSDP group, store in weights dict
        weights[("full", my_layer)] = await fsdp_allgather_in_group(weights[my_layer])

        # Forward
        act_out = model.forward(my_layer, activations[(my_layer, b)],
                                weights[("full", my_layer)])
        del weights[("full", my_layer)]

        if pipeline_stage == num_stages - 1:
            grad_activations[(my_layer + 1, b)] = model.loss(act_out)
        else:
            await model.pass_to(next_stage_rank, act_out)

    # --- Backward for all micro-batches (reverse order) ---
    for b in range(model.BATCHES - 1, -1, -1):
        if pipeline_stage == num_stages - 1:
            ga_out = grad_activations[(my_layer + 1, b)]
            del grad_activations[(my_layer + 1, b)]
        else:
            ga_out = await model.receive(next_stage_rank)

        act_in = activations[(my_layer, b)]
        del activations[(my_layer, b)]

        # AllGather weight for backward
        weights[("full", my_layer)] = await fsdp_allgather_in_group(weights[my_layer])

        # Backward
        wg, ga_in = model.backward(my_layer, act_in, ga_out,
                                   weights[("full", my_layer)])
        del weights[("full", my_layer)]

        if pipeline_stage > 0:
            await model.pass_to(prev_stage_rank, ga_in)

        # Accumulate weight grads
        if my_layer in grad_weights:
            grad_weights[my_layer] = grad_weights[my_layer] + wg
        else:
            grad_weights[my_layer] = wg

    # ScatterReduce accumulated gradients within FSDP group
    grad_weights[my_layer] = await fsdp_scatterreduce_in_group(grad_weights[my_layer])

    # Update local shard
    weights[my_layer], opt_states[my_layer] = model.update(
        my_layer, grad_weights[my_layer], weights[my_layer], opt_states[my_layer]
    )
    del grad_weights[my_layer]

    # Set final weights
    for l in range(model.LAYERS):
        if l == my_layer:
            model.set_final_weight(l, weights[my_layer])
        else:
            model.set_final_weight(l, Weight(l, 1, frozenset({0}), 1))

    return model
