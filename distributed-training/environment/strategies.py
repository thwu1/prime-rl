"""
Distributed training strategies to implement.

Prerequisites:
  1. Build cost model:  cd /app/native && make && ./cost_model_gen hw_spec.bin /app/cost_model.py
  2. Query configs:     sqlite3 /app/cluster.db "SELECT * FROM strategy_config"
  3. View topology:     jq '.strategies.pipeline_fsdp.pipeline' /app/topology.json

Each async function receives a Model instance. Study /app/lib.py for the full
Model API. After training, call model.set_final_weight(layer, weight) for
every layer so Model.check() can verify correctness.
"""

from lib import Model, Dist


async def ddp(model: Model) -> Model:
    """
    Distributed Data Parallel.

    Query cluster.db for rank count, layer count, batch count, and budgets.
    Each rank holds a full copy of all weights and processes one batch.
    Gradients are allreduced across ranks before the weight update.
    """
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()
    raise NotImplementedError("Implement DDP")


async def fsdp(model: Model) -> Model:
    """
    Fully Sharded Data Parallel (ZeRO-3).

    Query cluster.db for configuration. Weights, gradients, and optimizer
    states are sharded across ranks. Allgather weights before forward/backward,
    scatter-reduce gradients after backward.
    """
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()
    raise NotImplementedError("Implement FSDP")


async def pipeline_fsdp(model: Model) -> Model:
    """
    Pipeline Parallelism + FSDP.

    Query cluster.db for configuration and /app/topology.json for the
    pipeline stage layout. Ranks are organized into pipeline stages and
    data-parallel groups. Each stage owns a subset of layers. Weights are
    sharded across all ranks. Use p2p for inter-stage activation transfer.
    """
    weights, opt_states, activations, grad_activations, grad_weights = model.storage()
    raise NotImplementedError("Implement Pipeline + FSDP")
