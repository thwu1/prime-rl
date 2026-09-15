#!/bin/bash

set -e

# Build Stockfish from source
cd /app/stockfish/src
make -j$(nproc) build ARCH=x86-64
cd /app

# Deploy the TT codec solution
cp /solution/tt_codec_solution.py /app/tt_codec.py

# Smoke-test: verify Stockfish binary works
echo -e "uci\nquit" | timeout 10 /app/stockfish/src/stockfish | head -1

# Smoke-test: verify codec correctness
python3 -c "
import sys
sys.path.insert(0, '/app')
import tt_codec as tt

# Constants
assert tt.DEPTH_NONE == -3
assert tt.DEPTH_UNSEARCHED == -2
assert tt.MAX_PLY == 246
assert tt.BOUND_EXACT == 3
assert tt.CLUSTER_SIZE == 3
assert tt.VALUE_NONE == 32002
assert tt.VALUE_TB_WIN_IN_MAX_PLY == 31507
assert tt.VALUE_TB == 31753
assert tt.VALUE_MATE_IN_MAX_PLY == 31754

# genBound8 round-trip
for gen in range(32):
    for bound in range(4):
        for pv in [True, False]:
            packed = tt.pack_gen_bound(gen, bound, pv)
            g, b, p = tt.unpack_gen_bound(packed)
            assert (g, b, p) == (gen, bound, pv)

# Entry encode/decode round-trip
data = tt.encode_entry(0x1234567890ABCDEF, 10, True, tt.BOUND_EXACT, 0x1234, 100, 150, 5)
assert len(data) == 10
d = tt.decode_entry(data)
assert d['key16'] == 0xCDEF
assert d['depth'] == 10
assert d['value'] == 100

# value_to_tt / value_from_tt
assert tt.value_to_tt(100, 5) == 100
assert tt.value_to_tt(31600, 7) == 31607
assert tt.value_to_tt(-31600, 7) == -31607
assert tt.value_from_tt(31995, 3, 0) == 31992
assert tt.value_from_tt(31900, 5, 90) == tt.VALUE_TB_WIN_IN_MAX_PLY - 1
assert tt.value_from_tt(tt.VALUE_NONE, 5, 0) == tt.VALUE_NONE

# Cluster index
assert tt.cluster_index(0, 1024) == 0
assert tt.cluster_index(0xFFFFFFFFFFFFFFFF, 524288) == 524287

# Relative age with wrapping
gb = tt.pack_gen_bound(5, tt.BOUND_EXACT, True)
assert tt.relative_age(10, gb) == 5
assert tt.relative_age(3, gb) == 30

# Empty entry
e = tt.empty_entry()
assert e['depth8'] == 0 and e['key16'] == 0

# Probe empty cluster
cluster = [tt.empty_entry() for _ in range(3)]
hit, data, idx = tt.simulate_tt_probe(cluster, 0x1234, 0)
assert hit is False

# Store and probe
tt.simulate_tt_store(cluster, 0xBEEF, 100, True, tt.BOUND_EXACT, 10, 0x1234, 50, 0)
hit, data, idx = tt.simulate_tt_probe(cluster, 0xBEEF, 0)
assert hit is True
assert data['value'] == 100

# Move preservation
tt.simulate_tt_store(cluster, 0xBEEF, 200, False, tt.BOUND_LOWER, 15, 0, 60, 0)
assert cluster[idx]['move16'] == 0x1234  # preserved

# Hashfull
clusters = [[tt.empty_entry() for _ in range(3)] for _ in range(5)]
assert tt.hashfull(clusters, 0, 0) == 0

print('All solution smoke tests passed')
"
