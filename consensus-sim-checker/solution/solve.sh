#!/bin/bash

# Apply all fixes to the buggy simulation framework
cp /solution/prng.py /app/dsim/prng.py
cp /solution/quorums.py /app/dsim/quorums.py
cp /solution/packet_simulator.py /app/dsim/packet_simulator.py
cp /solution/state_checker.py /app/dsim/state_checker.py
cp /solution/liveness.py /app/dsim/liveness.py

# Verify fixes are correct
cd /app
python3 -c "
from dsim.quorums import compute_quorums
q2 = compute_quorums(2)
assert q2['replication'] == 2, f'R=2 fix failed: {q2}'
q3 = compute_quorums(3)
assert q3['replication'] == 2, f'R=3 fix failed: {q3}'
q5 = compute_quorums(5)
assert q5['replication'] == 3, f'R=5 fix failed: {q5}'
print('Quorum fixes verified')
"

python3 -c "
from dsim.prng import DeterministicPRNG
p = DeterministicPRNG(42)
seen = set()
for _ in range(10000):
    seen.add(p.range_inclusive(0, 3))
assert seen == {0,1,2,3}, f'range_inclusive fix failed: {seen}'
print('PRNG range_inclusive fix verified')
"

python3 -c "
from dsim.state_checker import StateChecker, SafetyViolation
sc = StateChecker(2)
sc.on_commit(0, 1, checksum=100, parent_checksum=0)
try:
    sc.on_commit(0, 1, checksum=999, parent_checksum=0)
    assert False, 'Should have raised SafetyViolation'
except SafetyViolation:
    pass
print('State checker recommit fix verified')
"

python3 -c "
from dsim.liveness import detect_repair_deadlock
available = {0: {5}, 1: {6}, 2: {5, 6}}
stuck = detect_repair_deadlock(available, {5, 6})
assert len(stuck) == 0, f'False positive: {stuck}'
print('Liveness deadlock detector fix verified')
"

python3 -c "
from dsim.packet_simulator import PacketSimulator, PacketSimulatorOptions
for seed in range(50):
    opts = PacketSimulatorOptions(
        node_count=5,
        one_way_delay_mean=10.0,
        one_way_delay_min=1.0,
        partition_mode='uniform_size',
        partition_probability=(100, 100),
        unpartition_probability=(0, 100),
    )
    sim = PacketSimulator(opts, seed)
    sim.tick()
    p = sim.get_partition()
    t = sum(p)
    f = len(p) - t
    assert t >= 1 and f >= 1, f'Partition fix failed seed={seed}: {p}'
print('Packet simulator partition fix verified')
"
