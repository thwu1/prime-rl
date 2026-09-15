"""
Solution implementations for the three distributed training strategies.
"""

from lib import Model, Dist


async def ddp(model: Model) -> Model:
    """Distributed Data Parallel."""
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    # Each rank loads full weights and processes one batch
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l)
    activations[0] = model.get_activation([model.rank])

    # Forward
    for l in range(model.LAYERS):
        activations[l + 1] = model.forward(l, activations[l], weights[l])

    # Backward
    grad_activations[model.LAYERS] = model.loss(activations[model.LAYERS])
    for l in range(model.LAYERS - 1, -1, -1):
        grad_weights[l], grad_activations[l] = model.backward(
            l, activations[l], grad_activations[l + 1], weights[l]
        )
        del grad_activations[l + 1], activations[l]

    # AllReduce gradients and update
    for l in range(model.LAYERS):
        grad_weights[l] = await model.allreduce(grad_weights[l], l)
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l], opt_states[l]
        )

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


async def fsdp(model: Model) -> Model:
    """Fully Sharded Data Parallel."""
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    # Each rank processes one batch, loads sharded weights
    activations[0] = model.get_activation([model.rank])
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.load_weights(l, model.rank, model.RANKS)

    # Forward: allgather weights, forward, delete gathered weights
    for l in range(model.LAYERS):
        weights[l, 0] = await model.allgather(weights[l], l)
        activations[l + 1] = model.forward(l, activations[l], weights[l, 0])
        del weights[l, 0]

    # Backward: allgather weights, backward, scatterreduce grads
    grad_activations[model.LAYERS] = model.loss(activations[model.LAYERS])
    del activations[model.LAYERS]

    for l in range(model.LAYERS - 1, -1, -1):
        weights[l, 0] = await model.allgather(weights[l], l)
        grad_weights[l], grad_activations[l] = model.backward(
            l, activations[l], grad_activations[l + 1], weights[l, 0]
        )
        grad_weights[l] = await model.scatterreduce(grad_weights[l], l)
        del grad_activations[l + 1], activations[l], weights[l, 0]

    # Update with sharded weights and sharded grads
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l], opt_states[l]
        )

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model


async def pipeline_fsdp(model: Model) -> Model:
    """Pipeline Parallelism + FSDP."""
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()

    # Layout: 4 pipeline stages x 4 data-parallel groups
    per_rank = model.LAYERS // (model.RANKS // 4)
    my_layers = [l + ((model.rank % 4) * per_rank) for l in range(per_rank)]

    # All ranks load sharded weights for ALL layers
    for l in range(model.LAYERS):
        weights[l, 0], opt_states[l, 0] = model.load_weights(
            l, model.rank, model.RANKS
        )

    def empty_grad(layer):
        return model.fake_grad(layer, [])

    # ---- Forward pass ----
    for l in range(model.LAYERS):
        # Receive activation from previous pipeline stage (or load input)
        if l == my_layers[0]:
            if model.rank % 4 == 0:
                activations[0] = model.get_activation([model.rank // 4])
            else:
                activations[l] = await model.receive()

        # All 16 ranks participate in allgather for every layer
        weights[l] = await model.allgather(weights[l, 0], l)

        # Only compute forward for owned layer
        if l in my_layers:
            activations[l + 1] = model.forward(l, activations[l], weights[l])
        del weights[l]

        # Send activation to next pipeline stage (or compute loss)
        if l == my_layers[-1]:
            if model.rank % 4 == 3:
                grad_activations[model.LAYERS] = model.loss(
                    activations[model.LAYERS]
                )
            else:
                await model.pass_to(model.rank + 1, activations[l + 1])

    # ---- Backward pass ----
    for l in reversed(range(model.LAYERS)):
        # Receive grad from next pipeline stage
        if l == my_layers[-1]:
            if model.rank % 4 != 3:
                grad_activations[l + 1] = await model.receive()

        # All 16 ranks participate in allgather
        weights[l] = await model.allgather(weights[l, 0], l)

        if l in my_layers:
            grad_weights[l], grad_activations[l] = model.backward(
                l, activations[l], grad_activations[l + 1], weights[l]
            )
            del grad_activations[l + 1], activations[l]
            # Scatterreduce: distribute gradient shards
            grad_weights[l] = await model.scatterreduce(grad_weights[l], l)
        else:
            # Non-owning ranks contribute empty gradient
            grad_weights[l] = await model.scatterreduce(empty_grad(l), l)
        del weights[l]

        # Send grad to previous pipeline stage
        if model.rank % 4 != 0 and l == my_layers[0]:
            await model.pass_to(model.rank - 1, grad_activations[l])

    # ---- Update all layers (each rank has shards of every layer) ----
    for l in range(model.LAYERS):
        weights[l], opt_states[l] = model.update(
            l, grad_weights[l], weights[l, 0], opt_states[l, 0]
        )

    for l in range(model.LAYERS):
        model.set_final_weight(l, weights[l])
    return model
