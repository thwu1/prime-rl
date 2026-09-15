A distributed training simulator is provided at `/app/simulator.py`. It models multi-GPU training of neural networks using asyncio, tracking memory usage and step counts without requiring actual GPUs. The simulator provides: `Model` (per-rank state with `forward`, `backward`, `loss`, `update`, `load_weights`, `get_activation`), communication primitives (`allreduce`, `allgather`, `scatterreduce`, `pass_to`/`receive`), and `Weight`/`WeightGrad`/`Activation`/`GradActivation` data types.

Implement 5 distributed training strategies in `/app/strategies.py`, replacing each `raise NotImplementedError`. Each strategy must:

1. Pass `Model.check()` (correct final weights, version >= 1 for all layers)
2. Meet the step count target (total steps across the slowest rank)
3. Meet the peak memory target (max memory across all ranks at any point)

**Strategies to implement:**

| # | Strategy | Ranks | Layers | Batches | Max Steps | Max Memory |
|---|----------|-------|--------|---------|-----------|------------|
| 1 | `basic` (standard training) | 1 | 2 | 4 | 12 | 4,600,000 |
| 2 | `grad_accum` (gradient accumulation) | 1 | 2 | 4 | 32 | 3,800,000 |
| 3 | `ddp` (distributed data parallel) | 4 | 2 | 4 | 14 | 3,400,000 |
| 4 | `fsdp` (fully-sharded data parallel) | 4 | 6 | 4 | 50 | 5,200,000 |
| 5 | `pipeline_fsdp` (pipeline + FSDP) | 16 | 4 | 4 | 90 | 2,400,000 |

Memory is tracked via 5 model storage dicts: `weights`, `opt_states`, `activations`, `grad_activations`, `grad_weights`. All persistent tensors (activations saved for backward, gathered weights, etc.) must be stored in these dicts using any hashable key. Delete entries (`del dict[key]`) when no longer needed. Memory is measured at each operation (`forward`, `backward`, `loss`, `update`, `load_weights`, `get_activation`, and communication calls).

Key API: `forward(layer, activation, weight)` requires full (ungathered) weights and returns next-layer activation. `backward(layer, activation, grad_activation, weight)` returns `(weight_grad, grad_activation)`. `update(layer, weight_grad, weight, opt_state)` requires gradients summed over ALL batches. `allreduce(grad, tag)` sums weight gradients across all ranks. `allgather(weight, tag)` reconstructs full weights from shards. `scatterreduce(grad, tag)` distributes gradient shards. `pass_to(rank, data)` / `receive(rank)` for point-to-point.

The combined Pipeline+FSDP strategy (strategy 5) is the most challenging: 16 ranks are organized into 4 pipeline stages of 4 FSDP ranks each. Each stage owns one layer. Weights are sharded across the 4 FSDP ranks within each stage using `load_weights(layer, fsdp_rank, fsdp_group_size)`. Since the global communication primitives require all ranks to participate, intra-group FSDP operations (allgather, scatter-reduce) must be implemented via point-to-point within each group. Activations flow between pipeline stages via point-to-point communication between corresponding ranks.

Run tests with `cd /app && python3 -m pytest /tests/test_state.py -v`.