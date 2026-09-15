#!/bin/bash


cp /solution/block_manager_impl.py /app/block_manager.py

cd /app
python3 -c "
from block_manager import BlockManager
from block_manager_interface import BlockManagerConfig, PreemptionMode

config = BlockManagerConfig(
    num_gpu_blocks=16, num_cpu_blocks=8, block_size=4,
    enable_prefix_caching=True, preemption_mode=PreemptionMode.SWAP
)
bm = BlockManager(config)

assert bm.allocate(1, list(range(10)))
snap = bm.get_memory_snapshot()
assert snap.gpu_blocks_used == 3
assert snap.gpu_blocks_free == 13

bm.fork(1, 2)
bm.append_tokens(2, [99])
snap = bm.get_memory_snapshot()
assert snap.cow_copies == 1
assert snap.gpu_blocks_used == 4

bm.free(1)
bm.free(2)
bm.allocate(3, list(range(8)))
snap = bm.get_memory_snapshot()
assert snap.prefix_cache_hits >= 1

print('BlockManager reference implementation verified successfully')
"
