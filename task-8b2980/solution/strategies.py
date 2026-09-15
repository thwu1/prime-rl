"""
Distributed training strategy implementations.
"""

from lib import Model


async def fsdp(model: Model) -> Model:
    """
    Fully-Sharded Data Parallel.
    Each rank processes one batch with weights sharded across ranks.
    Uses allgather to reconstruct full weights, scatterreduce for gradients.
    """
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    # Each rank processes its own batch
    activations[0] = model.get_activation([model.rank])

    # Load sharded weights and optimizer states
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l, model.rank, model.RANKS)

    # Forward pass: gather full weights, compute, delete gathered copy
    for l in range(model.LAYERS):
        weights[l, "full"] = await model.allgather(weights[l], l)
        activations[l + 1] = model.forward(l, activations[l], weights[l, "full"])
        del weights[l, "full"]

    # Loss
    grad_activations[model.LAYERS] = model.loss(activations[model.LAYERS])
    del activations[model.LAYERS]

    # Backward pass: gather weights, compute grads, scatter-reduce, free memory
    for l in range(model.LAYERS - 1, -1, -1):
        weights[l, "full"] = await model.allgather(weights[l], l)
        grad_weights[l], grad_activations[l] = model.backward(
            l, activations[l], grad_activations[l + 1], weights[l, "full"]
        )
        grad_weights[l] = await model.scatterreduce(grad_weights[l], l)
        del grad_activations[l + 1], activations[l], weights[l, "full"]

    # Update with sharded weights and sharded gradients
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l], opt_states[l]
        )

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


async def gpipe(model: Model) -> Model:
    """
    GPipe pipeline schedule.
    Layers partitioned across pipeline stages.
    All microbatch forwards, then all microbatch backwards.
    """
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    # Determine this rank's layers
    per_rank = model.LAYERS // model.RANKS
    my_layers = [l + (model.rank * per_rank) for l in range(per_rank)]

    # Load full weights for assigned layers
    for l in my_layers:
        weights[l], opt_states[l] = model.load_weights(l)

    # Forward all microbatches through the pipeline
    for mb in range(model.BATCHES):
        if model.rank == 0:
            activations[0, mb] = model.get_activation([mb])
        else:
            activations[my_layers[0], mb] = await model.receive()

        for l in my_layers:
            activations[l + 1, mb] = model.forward(l, activations[l, mb], weights[l])

        if model.rank != model.RANKS - 1:
            await model.pass_to(model.rank + 1, activations[my_layers[-1] + 1, mb])

    # Backward all microbatches through the pipeline
    for mb in range(model.BATCHES):
        if model.rank == model.RANKS - 1:
            grad_activations[model.LAYERS, mb] = model.loss(
                activations[model.LAYERS, mb]
            )
        else:
            grad_activations[my_layers[-1] + 1, mb] = await model.receive()

        for l in reversed(my_layers):
            grad_weights[l, mb], grad_activations[l, mb] = model.backward(
                l, activations[l, mb], grad_activations[l + 1, mb], weights[l]
            )
            del grad_activations[l + 1, mb], activations[l, mb]

        if model.rank != 0:
            await model.pass_to(model.rank - 1, grad_activations[my_layers[0], mb])

    # Accumulate gradients across microbatches and update
    for l in reversed(my_layers):
        for mb in range(model.BATCHES):
            if mb == 0:
                grad_weights[l] = grad_weights[l, 0]
            else:
                grad_weights[l] = grad_weights[l] + grad_weights[l, mb]
            del grad_weights[l, mb]
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l], opt_states[l]
        )

    for l in my_layers:
        model.set_final_weight(l, weights[l])
    return model


async def pipeline_fsdp(model: Model) -> Model:
    """
    Combined Pipeline Parallelism + FSDP.
    Pipeline stage = rank % 4, batch = rank // 4.
    All ranks participate in global allgather/scatterreduce.
    Point-to-point between adjacent pipeline stages.
    """
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    # Pipeline stage mapping: rank % 4 -> layer index
    num_stages = model.RANKS // (model.RANKS // model.LAYERS)
    per_rank = model.LAYERS // num_stages
    my_layers = [l + ((model.rank % num_stages) * per_rank) for l in range(per_rank)]

    # Load sharded weights for ALL layers (sharded across all ranks)
    for l in range(model.LAYERS):
        weights[l, 0], opt_states[l, 0] = model.load_weights(l, model.rank, model.RANKS)

    def empty_grad(layer):
        return model.fake_grad(layer, [])

    # Forward pass
    for l in range(model.LAYERS):
        # Receive activation from previous pipeline stage
        if l == my_layers[0]:
            if model.rank % num_stages == 0:
                activations[0] = model.get_activation([model.rank // num_stages])
            else:
                activations[l] = await model.receive()

        # All ranks gather the full weight for this layer
        weights[l] = await model.allgather(weights[l, 0], l)

        # Only compute forward for assigned layers
        if l in my_layers:
            activations[l + 1] = model.forward(l, activations[l], weights[l])
        del weights[l]

        # Send activation to next pipeline stage
        if l == my_layers[-1]:
            if model.rank % num_stages == num_stages - 1:
                grad_activations[model.LAYERS] = model.loss(
                    activations[model.LAYERS]
                )
            else:
                await model.pass_to(model.rank + 1, activations[l + 1])

    # Backward pass
    for l in reversed(range(model.LAYERS)):
        # Receive gradient from next pipeline stage
        if l == my_layers[-1]:
            if model.rank % num_stages != num_stages - 1:
                grad_activations[l + 1] = await model.receive()

        # All ranks gather the full weight
        weights[l] = await model.allgather(weights[l, 0], l)

        if l in my_layers:
            # Compute backward for assigned layers
            grad_weights[l], grad_activations[l] = model.backward(
                l, activations[l], grad_activations[l + 1], weights[l]
            )
            del grad_activations[l + 1], activations[l]
            grad_weights[l] = await model.scatterreduce(grad_weights[l], l)
        else:
            # Non-computing ranks pass empty gradients
            grad_weights[l] = await model.scatterreduce(empty_grad(l), l)
        del weights[l]

        # Send gradient to previous pipeline stage
        if model.rank % num_stages != 0 and l == my_layers[0]:
            await model.pass_to(model.rank - 1, grad_activations[l])

    # Update all layers (every rank has a shard of every layer)
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l, 0], opt_states[l, 0]
        )

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model
